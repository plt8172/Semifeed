// Semifeed 승인·게시 Worker
//
// fetch:     Slack [승인][반려] 버튼 콜백. 서명을 검증하고 바로 200을 돌려준 뒤
//            (Slack은 3초 안에 응답을 요구한다) 게시는 waitUntil에서 이어서 한다.
// scheduled: 5분마다 Instagram 처리가 늦었던 게시를 마무리하고, 매일 한 번 토큰을 갱신한다.

import { InstagramClient, isRateLimit, refreshToken } from "./instagram";
import { Block, cardBlocks, reviewActions, updateMessage, verifySlackSignature, withStatus } from "./slack";

export interface Env {
  SLACK_SIGNING_SECRET: string;
  SLACK_BOT_TOKEN: string;
  IG_ACCESS_TOKEN: string;
  IG_USER_ID: string;
  IG_API_VERSION: string;
  CARDS_BASE_URL: string;
  STATE: KVNamespace;
}

// 버튼 value: "<날짜>/<카드 id>". 경로 조작을 막기 위해 형식을 엄격히 제한한다.
const KEY_PATTERN = /^\d{4}-\d{2}-\d{2}\/[A-Za-z0-9_-]{1,64}$/;
const REFRESH_CRON = "0 18 * * *";
// 무료 플랜의 waitUntil은 응답 후 약 30초까지 이어진다. 그 안에서 끝내고 나머지는 Cron에 넘긴다.
const POLL_DEADLINE_MS = 20_000;
// 승인 직후 처리 상태 확인 간격. Meta 앱 호출 한도(앱 사용자 1명 기준 시간당 약 200회)를 넘지 않게 넉넉히 둔다.
const POLL_INTERVAL_MS = 5_000;
// Cron(5분마다)에서는 한 번 실행에 상태를 한 번만 확인한다.
const CRON_POLL = { deadlineMs: 20_000, intervalMs: 60_000 };
// 호출 한도에 걸리면 이 시간 동안 Instagram을 부르지 않고 기다렸다가 Cron이 자동으로 이어 간다.
const RATE_LIMIT_COOLDOWN_MS = 30 * 60 * 1000;
const COOLDOWN_KEY = "ig_cooldown_until";
// 이 시간이 지나도 끝나지 않은 작업은 실패로 본다. 컨테이너는 24시간 뒤 만료된다.
const PENDING_GIVE_UP_MS = 12 * 60 * 60 * 1000;
const PENDING_TTL_S = 24 * 3600;

interface Pending {
  key: string;
  /** 이미지 컨테이너. 만들기 전에 한도에 걸렸으면 비어 있다. */
  containerId?: string;
  caption?: string;
  /** media_publish를 부른 시각. 이후에는 다시 발행하기 전에 이미 게시됐는지부터 확인한다. */
  publishAttemptedAt?: number;
  /** 호출 한도 초과를 Slack에 알린 시각. */
  rateLimitedAt?: number;
  channel: string;
  ts: string;
  user: string;
  blocks: Block[];
  createdAt: number;
}

interface SlackAction {
  type: string;
  user: { id: string };
  channel: { id: string };
  message: { ts: string; blocks: Block[] };
  actions: { action_id: string; value: string }[];
}

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    if (request.method !== "POST") return new Response("semifeed worker", { status: 200 });

    const body = await request.text();
    const valid = await verifySlackSignature(
      env.SLACK_SIGNING_SECRET,
      request.headers.get("X-Slack-Request-Timestamp"),
      body,
      request.headers.get("X-Slack-Signature"),
    );
    if (!valid) return new Response("invalid signature", { status: 401 });

    const raw = new URLSearchParams(body).get("payload");
    if (!raw) return new Response("", { status: 200 });
    const payload = JSON.parse(raw) as SlackAction;
    const action = payload.actions?.[0];
    if (payload.type !== "block_actions" || !action || !KEY_PATTERN.test(action.value)) {
      return new Response("", { status: 200 });
    }

    ctx.waitUntil(handleAction(env, action.action_id, action.value, payload));
    return new Response("", { status: 200 });
  },

  async scheduled(event: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    if (event.cron === REFRESH_CRON) {
      ctx.waitUntil(refreshStoredToken(env));
    } else {
      ctx.waitUntil(processPending(env));
    }
  },
};

export async function handleAction(
  env: Env,
  actionId: string,
  key: string,
  payload: SlackAction,
  poll = { deadlineMs: POLL_DEADLINE_MS, intervalMs: POLL_INTERVAL_MS },
): Promise<void> {
  const channel = payload.channel.id;
  const ts = payload.message.ts;
  const user = payload.user.id;
  const base = cardBlocks(payload.message.blocks ?? []);
  const update = (status: string, actions?: Block) =>
    updateMessage(env.SLACK_BOT_TOKEN, channel, ts, status, withStatus(base, status, actions));

  // 같은 카드를 두 번 누르거나 두 사람이 동시에 눌러도 한 번만 게시되게 한다.
  // 진행 중인 작업(pending)이 있으면 그 작업이 끝날 때까지 새로 시작하지 않는다.
  const stateKey = `card:${key}`;
  const state = await env.STATE.get(stateKey);
  if (state === "publishing" || state === "published") return;
  if (await env.STATE.get(`pending:${key}`)) return;

  if (actionId === "reject") {
    await env.STATE.put(stateKey, "rejected");
    await update(`❌ 반려됨 · <@${user}>`);
    return;
  }
  if (actionId !== "approve") return;

  await env.STATE.put(stateKey, "publishing", { expirationTtl: PENDING_TTL_S });
  const pending: Pending = { key, channel, ts, user, blocks: base, createdAt: Date.now() };
  await savePending(env, pending);
  await update(`⏳ 게시 중… · <@${user}> 승인`);

  const done = await advance(env, pending, poll);
  if (!done && !pending.rateLimitedAt) {
    // Instagram 처리가 늦으면 5분 Cron이 이어받는다.
    await update(`⏳ Instagram이 이미지를 처리하는 중입니다. 몇 분 안에 자동으로 게시됩니다 · <@${user}> 승인`);
  }
}

/** 게시를 주어진 시간 안에서 진행한다. 발행했거나 실패 처리했으면 true, Cron에 넘겼으면 false. */
async function advance(env: Env, pending: Pending, poll: { deadlineMs: number; intervalMs: number }): Promise<boolean> {
  const started = Date.now();
  try {
    if (await coolingDown(env)) return false;
    if (Date.now() - pending.createdAt > PENDING_GIVE_UP_MS) throw new Error("Instagram 게시가 12시간 넘게 끝나지 않았습니다");
    const instagram = new InstagramClient(await currentToken(env), env.IG_USER_ID, env.IG_API_VERSION);

    if (!pending.containerId) {
      if (pending.caption === undefined) pending.caption = (await fetchCard(env, pending.key)).caption;
      pending.containerId = await instagram.createContainer(`${env.CARDS_BASE_URL}/${pending.key}.jpg`, pending.caption);
      await savePending(env, pending);
    }
    for (;;) {
      // 지난번 발행 호출이 오류를 냈더라도 실제로는 게시됐을 수 있어, 발행 전에 늘 상태부터 본다.
      const status = await instagram.containerStatus(pending.containerId);
      if (status.code === "PUBLISHED") {
        await markPublished(env, instagram, pending);
        return true;
      }
      if (status.code === "FINISHED") {
        await finishPublish(env, instagram, pending as Pending & { containerId: string });
        return true;
      }
      if (status.code !== "IN_PROGRESS") throw new Error(`컨테이너 ${status.code}: ${status.detail ?? ""}`);
      if (poll.deadlineMs - (Date.now() - started) <= poll.intervalMs) return false;
      await sleep(poll.intervalMs);
    }
  } catch (error) {
    if (isRateLimit(error)) {
      await deferForRateLimit(env, pending, error);
      return false;
    }
    await failPublish(env, pending, error);
    return true;
  }
}

async function savePending(env: Env, pending: Pending): Promise<void> {
  await env.STATE.put(`pending:${pending.key}`, JSON.stringify(pending), { expirationTtl: PENDING_TTL_S });
}

async function coolingDown(env: Env): Promise<boolean> {
  return Number((await env.STATE.get(COOLDOWN_KEY)) ?? 0) > Date.now();
}

/** 호출 한도에 걸리면 버튼을 되살리지 않고(재승인 → 중복 게시 방지) 잠시 쉬었다가 Cron이 이어 간다. */
async function deferForRateLimit(env: Env, pending: Pending, error: unknown): Promise<void> {
  const message = error instanceof Error ? error.message : String(error);
  console.warn("instagram rate limited, cooling down", pending.key, message);
  await env.STATE.put(COOLDOWN_KEY, String(Date.now() + RATE_LIMIT_COOLDOWN_MS), { expirationTtl: RATE_LIMIT_COOLDOWN_MS / 1000 + 60 });
  const notify = !pending.rateLimitedAt;
  pending.rateLimitedAt ??= Date.now();
  await savePending(env, pending);
  if (notify) {
    const status = `⏳ Instagram API 호출 한도에 걸렸습니다. 30분쯤 뒤 자동으로 이어서 게시하니 다시 승인하지 마세요 · <@${pending.user}> 승인`;
    await updateMessage(env.SLACK_BOT_TOKEN, pending.channel, pending.ts, status, withStatus(pending.blocks, status));
  }
}

async function finishPublish(env: Env, instagram: InstagramClient, pending: Pending & { containerId: string }): Promise<void> {
  pending.publishAttemptedAt = Date.now();
  await savePending(env, pending);
  let mediaId: string | undefined;
  try {
    mediaId = await instagram.publish(pending.containerId);
  } catch (error) {
    // media_publish가 오류(특히 호출 한도)를 돌려줘도 게시는 된 경우가 있다. 확인되면 성공으로 처리한다.
    const status = await instagram.containerStatus(pending.containerId).catch(() => undefined);
    if (status?.code !== "PUBLISHED") throw error;
  }
  await markPublished(env, instagram, pending, mediaId);
}

async function markPublished(env: Env, instagram: InstagramClient, pending: Pending, mediaId?: string): Promise<void> {
  const permalink = mediaId ? await instagram.permalink(mediaId).catch(() => undefined) : undefined;
  await env.STATE.put(`card:${pending.key}`, "published");
  await env.STATE.delete(`pending:${pending.key}`);
  const link = permalink ? `<${permalink}|Instagram에서 보기>` : mediaId ? `media ${mediaId}` : "Instagram 프로필에서 확인";
  const status = `✅ 게시 완료 · ${link} · <@${pending.user}> 승인`;
  await updateMessage(env.SLACK_BOT_TOKEN, pending.channel, pending.ts, status, withStatus(pending.blocks, status));
}

async function failPublish(env: Env, target: Pick<Pending, "key" | "channel" | "ts" | "user" | "blocks" | "publishAttemptedAt">, error: unknown): Promise<void> {
  const message = error instanceof Error ? error.message : String(error);
  console.error("publish failed", target.key, message);
  await env.STATE.delete(`card:${target.key}`);
  await env.STATE.delete(`pending:${target.key}`);
  // 버튼을 되살려 원인을 고친 뒤 다시 승인할 수 있게 한다.
  // 발행까지 시도했다면 실제로 올라갔을 수 있으니 확인부터 하라고 알린다.
  const check = target.publishAttemptedAt ? " · 다시 승인하기 전에 Instagram에 이미 올라갔는지 확인하세요" : "";
  const status = `⚠️ 게시 실패: ${message}${check}`;
  await updateMessage(env.SLACK_BOT_TOKEN, target.channel, target.ts, status, withStatus(target.blocks, status, reviewActions(target.key)));
}

export async function processPending(env: Env, poll = CRON_POLL): Promise<void> {
  if (await coolingDown(env)) return;
  const list = await env.STATE.list({ prefix: "pending:" });
  for (const { name } of list.keys) {
    const raw = await env.STATE.get(name);
    if (!raw) continue;
    await advance(env, JSON.parse(raw) as Pending, poll);
    if (await coolingDown(env)) return;
  }
}

/** Cron이 갱신한 토큰이 KV에 있으면 그것을, 없으면 처음 등록한 Secret을 쓴다. */
async function currentToken(env: Env): Promise<string> {
  return (await env.STATE.get("ig_token")) ?? env.IG_ACCESS_TOKEN;
}

export async function refreshStoredToken(env: Env): Promise<void> {
  const refreshed = await refreshToken(await currentToken(env));
  await env.STATE.put("ig_token", refreshed.token);
  await env.STATE.put("ig_token_refreshed_at", new Date().toISOString());
  console.log("instagram token refreshed, expires in", refreshed.expiresIn, "s");
}

async function fetchCard(env: Env, key: string): Promise<{ caption: string }> {
  const response = await fetch(`${env.CARDS_BASE_URL}/${key}.json`, { cf: { cacheTtl: 0 } });
  if (!response.ok) throw new Error(`카드 메타데이터를 읽지 못했습니다 (${response.status})`);
  const card = (await response.json()) as { caption?: string };
  if (!card.caption) throw new Error("카드에 caption이 없습니다");
  return { caption: card.caption };
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
