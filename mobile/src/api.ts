export function resolveBaseUrl(value: string | undefined, dev: boolean, allowHttp: boolean): string {
  if (!value) throw new Error('mobile/.env에 EXPO_PUBLIC_API_URL을 설정해 주세요.');
  let url: URL;
  try { url = new URL(value); } catch { throw new Error('서버 주소를 확인해 주세요.'); }
  if (url.username || url.password || url.search || url.hash || !['', '/'].includes(url.pathname)) throw new Error('서버 주소에는 인증정보나 경로를 넣을 수 없습니다.');
  const parts = url.hostname.split('.').map(Number);
  const ipv4 = parts.length === 4 && parts.every(p => Number.isInteger(p) && p >= 0 && p <= 255);
  const privateHost = url.hostname === 'localhost' || (ipv4 && (parts[0] === 10 || parts[0] === 127 || (parts[0] === 192 && parts[1] === 168) || (parts[0] === 172 && parts[1] >= 16 && parts[1] <= 31)));
  if (url.protocol !== 'https:' && !(dev && allowHttp && url.protocol === 'http:' && privateHost)) throw new Error('HTTPS 서버 주소가 필요합니다. HTTP는 개발 중 사설망에서만 허용됩니다.');
  return url.origin;
}
export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) { super(message); this.status = status; }
}
export class ApiClient {
  baseUrl: string;
  token = '';
  closed = false;
  private controllers = new Set<AbortController>();
  private fetcher: typeof fetch;
  private expired: () => void;
  constructor(baseUrl: string, expired: () => void = () => {}, fetcher: typeof fetch = fetch) {
    this.baseUrl = baseUrl; this.expired = expired; this.fetcher = fetcher;
  }
  close() { this.closed = true; this.token = ''; this.controllers.forEach(c => c.abort()); this.controllers.clear(); }
  async request<T>(path: string, body?: unknown): Promise<T> {
    if (this.closed) throw new ApiError(401, '다시 로그인해 주세요.');
    if (!(path.startsWith('/api/') || path === '/health') || path.includes('://')) throw new Error('허용되지 않은 API 경로');
    const controller = new AbortController(); this.controllers.add(controller);
    const timeout = setTimeout(() => controller.abort(), 60000);
    const hadToken = Boolean(this.token);
    try {
      const response = await this.fetcher(this.baseUrl + path, {
        method: body === undefined ? 'GET' : 'POST', redirect: 'error', cache: 'no-store', signal: controller.signal,
        headers: { 'Content-Type': 'application/json', ...(this.token ? { Authorization: `Bearer ${this.token}` } : {}) },
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      });
      if (this.closed) throw new ApiError(401, '다시 로그인해 주세요.');
      if (!response.ok) {
        if (response.status === 401 && hadToken) { this.close(); this.expired(); }
        const messages: Record<number, string> = { 400: '선택 항목을 확인해 주세요.', 401: '로그인 정보를 확인해 주세요. 세션이 만료됐을 수도 있습니다.', 403: '계정 승인 또는 접근 권한을 확인해 주세요.', 404: '요청을 찾을 수 없습니다.', 409: '이미 처리됐거나 사용할 수 없는 값입니다. 목록을 새로고침해 주세요.', 422: '입력 형식·지역·미래 날짜를 확인해 주세요. 음성이라면 짧고 또렷하게 다시 말씀해 주세요.', 503: '기관 AI를 사용할 수 없습니다. 서버 설정·모델 설치를 확인하거나 담당자에게 문의해 주세요.' };
        throw new ApiError(response.status, messages[response.status] || '서버에서 처리하지 못했습니다.');
      }
      const result = await response.json() as T;
      if (this.closed) throw new ApiError(401, '다시 로그인해 주세요.');
      return result;
    } catch (error) {
      if (error instanceof ApiError) throw error;
      throw new ApiError(0, '서버 연결을 확인해 주세요. 요청을 보냈다면 목록에서 접수 여부를 확인한 뒤 재시도해 주세요.');
    } finally { clearTimeout(timeout); this.controllers.delete(controller); }
  }
}
