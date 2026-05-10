import axios from 'axios';

export const AUTH_ERROR_EVENT = 'nocturne:auth-error';

export const api = axios.create({
  baseURL: '/api'
});

// 请求拦截器：自动附加 Bearer Token 和 X-Namespace
api.interceptors.request.use((config) => {
  config.headers = config.headers ?? {};
  const token = localStorage.getItem('api_token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  const ns = localStorage.getItem('selected_namespace');
  if (ns && !config.url.startsWith('/review')) {
    config.headers['X-Namespace'] = ns;
  }
  return config;
});

// 响应拦截器：401 时清除 token 并触发重新认证
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response && error.response.status === 401) {
      localStorage.removeItem('api_token');
      window.dispatchEvent(new CustomEvent(AUTH_ERROR_EVENT));
    }
    return Promise.reject(error);
  }
);

const encodeId = (id) => encodeURIComponent(id);

// ============ Review API ============

export const getGroups = () =>
  api.get('/review/groups').then(res => res.data);

export const getGroupDiff = (nodeUuid) =>
  api.get(`/review/groups/${encodeId(nodeUuid)}/diff`).then(res => res.data);

export const rollbackGroup = (nodeUuid) =>
  api.post(`/review/groups/${encodeId(nodeUuid)}/rollback`, {}).then(res => res.data);

export const approveGroup = (nodeUuid) =>
  api.delete(`/review/groups/${encodeId(nodeUuid)}`).then(res => res.data);

export const clearAll = () =>
  api.delete('/review').then(res => res.data);

// ============ Browse API ============

export const getDomains = () =>
  api.get('/browse/domains').then(res => res.data);

export const getNamespaces = () =>
  api.get('/browse/namespaces').then(res => res.data);

// ============ Boot URI API ============

export const getBootUris = () =>
  api.get('/browse/boot-uris').then(res => res.data.uris);

export const toggleBootUri = (uri, enabled) =>
  api.put('/browse/boot-uris', { uri, enabled }).then(res => res.data);

export default api;
