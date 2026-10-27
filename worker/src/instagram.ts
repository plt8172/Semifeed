// Instagram API with Instagram Login (graph.instagram.com) 호출.
// 이미지 게시는 컨테이너 생성 → 처리 완료 확인 → 발행 세 단계다.

export type ContainerStatus = "FINISHED" | "IN_PROGRESS" | "ERROR" | "EXPIRED" | "PUBLISHED";

export class InstagramClient {
  private readonly base: string;

  constructor(private readonly token: string, private readonly userId: string, version: string) {
    this.base = `https://graph.instagram.com/${version}`;
  }

  async createContainer(imageUrl: string, caption: string): Promise<string> {
    const result = await this.call("POST", `${this.userId}/media`, { image_url: imageUrl, caption });
    return result.id as string;
  }

  async containerStatus(containerId: string): Promise<{ code: ContainerStatus; detail?: string }> {
    const result = await this.call("GET", containerId, { fields: "status_code,status" });
    return { code: result.status_code as ContainerStatus, detail: result.status as string | undefined };
  }

  async publish(containerId: string): Promise<string> {
    const result = await this.call("POST", `${this.userId}/media_publish`, { creation_id: containerId });
    return result.id as string;
  }

  async permalink(mediaId: string): Promise<string | undefined> {
    const result = await this.call("GET", mediaId, { fields: "permalink" });
    return result.permalink as string | undefined;
  }

  private async call(method: "GET" | "POST", path: string, params: Record<string, string>): Promise<Record<string, unknown>> {
    const query = new URLSearchParams(params);
    const url = method === "GET" ? `${this.base}/${path}?${query}` : `${this.base}/${path}`;
    const response = await fetch(url, {
      method,
      headers: { Authorization: `Bearer ${this.token}` },
      body: method === "POST" ? query : undefined,
    });
    const result = (await response.json()) as Record<string, unknown> & { error?: { message?: string } };
    if (!response.ok || result.error) {
      throw new Error(`Instagram ${path}: ${result.error?.message ?? response.status}`);
    }
    return result;
  }
}

/** 장기 토큰(60일)을 새 60일 토큰으로 바꾼다. 발급 후 24시간이 지나야 갱신된다. */
export async function refreshToken(token: string): Promise<{ token: string; expiresIn: number }> {
  const query = new URLSearchParams({ grant_type: "ig_refresh_token", access_token: token });
  const response = await fetch(`https://graph.instagram.com/refresh_access_token?${query}`);
  const result = (await response.json()) as { access_token?: string; expires_in?: number; error?: { message?: string } };
  if (!response.ok || !result.access_token) {
    throw new Error(`Instagram token refresh: ${result.error?.message ?? response.status}`);
  }
  return { token: result.access_token, expiresIn: result.expires_in ?? 0 };
}
