import { config } from '$lib/config';

const TOKEN_KEY = 'HELIOS_TOKEN';

export function getToken(): string | null {
  if (typeof localStorage === 'undefined') return null;
  return localStorage.getItem(TOKEN_KEY);
}

export function fetchWithAuth(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  const token = getToken();
  const headers = new Headers(init?.headers);
  if (token) {
    headers.set('Authorization', `Bearer ${token}`);
  }
  return fetch(input, { ...init, headers });
}

export function buildWsUrl(path: string): string {
  const base = config.heliosWsUrl.replace(/\/$/, '');
  return `${base}${path}`;
}

export function buildHttpUrl(path: string): string {
  const base = config.heliosApiUrl.replace(/\/$/, '');
  return `${base}${path}`;
}

export function buildSseUrl(path: string): string {
  const base = config.heliosApiUrl.replace(/\/$/, '');
  return `${base}${path}`;
}

export interface BridgeAuthTransport {
  type: 'query' | 'protocol' | 'cookie' | 'none';
  apply(url: string, token: string): string;
}

export const authTransports: Record<string, BridgeAuthTransport> = {
  query: {
    type: 'query',
    apply(url: string, token: string): string {
      const u = new URL(url);
      u.searchParams.set('token', token);
      return u.toString();
    }
  },
  protocol: {
    type: 'protocol',
    apply(url: string, _token: string): string {
      void _token;
      return url;
    }
  },
  cookie: {
    type: 'cookie',
    apply(url: string, _token: string): string {
      void _token;
      return url;
    }
  },
  none: {
    type: 'none',
    apply(url: string, _token: string): string {
      void _token;
      return url;
    }
  }
};

export function getAuthTransport(): BridgeAuthTransport {
  const mode = import.meta.env.PUBLIC_HELIOS_AUTH_TRANSPORT ?? 'query';
  return authTransports[mode] ?? authTransports.query;
}

export function applyAuthToUrl(url: string): string {
  const token = getToken();
  if (!token) return url;
  const transport = getAuthTransport();
  return transport.apply(url, token);
}

export async function checkHealth(): Promise<boolean> {
  try {
    const res = await fetchWithAuth(buildHttpUrl('/health'), { method: 'GET' });
    return res.ok;
  } catch {
    return false;
  }
}
