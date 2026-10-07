const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api/v1';

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {'Content-Type': 'application/json', ...(options.headers || {})},
    ...options,
  });
  if (!response.ok) throw new Error(await response.text());
  return response.status === 204 ? null : response.json();
}

export const api = {
  workspace: () => request('/workspace'),
  tasks: (params = '') => request(`/tasks${params}`),
  task: (id) => request(`/tasks/${id}`),
  createTask: (body) => request('/tasks', {method: 'POST', body: JSON.stringify(body)}),
  patchTask: (id, body) => request(`/tasks/${id}`, {method: 'PATCH', body: JSON.stringify(body)}),
  transitionTask: (id, action) => request(`/tasks/${id}/${action}`, {method: 'POST'}),
  completeTask: (id) => request(`/tasks/${id}/complete`, {method: 'POST'}),
  time: {
    today: () => request('/time/today'),
    start: () => request('/time/start', {method: 'POST'}),
    pause: () => request('/time/pause', {method: 'POST'}),
    resume: () => request('/time/resume', {method: 'POST'}),
    end: () => request('/time/end', {method: 'POST'}),
  },
  notifications: () => request('/notifications'),
  requests: () => request('/requests'),
  request: (id) => request(`/requests/${id}`),
  createRequest: (body) => request('/requests', {method: 'POST', body: JSON.stringify(body)}),
  requestAction: (id, action) => request(`/requests/${id}/${action}`, {method: 'POST'}),
  requestMessages: (id) => request(`/requests/${id}/messages`),
  addRequestMessage: (id, body) => request(`/requests/${id}/messages`, {method: 'POST', body: JSON.stringify(body)}),
  requestActivity: (id) => request(`/requests/${id}/activity`),
  taskActivity: (id) => request(`/tasks/${id}/activity`),
};
