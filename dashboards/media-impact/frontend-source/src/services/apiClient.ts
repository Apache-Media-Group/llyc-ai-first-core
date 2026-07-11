// frontend/src/services/apiClient.ts - Secure HTTP API Client Wrapper
import { auth } from '../firebase';

export const API_BASE_URL = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1' 
  ? 'http://localhost:8080' 
  : '';

/**
 * A secure fetch wrapper that:
 * 1. Resolves relative URLs to the target dynamic backend API.
 * 2. Injects 'Content-Type: application/json' automatically for JSON payloads.
 * 3. Reactive-extracts and injects the Firebase ID token in 'Authorization: Bearer <JWT>' if user is authenticated.
 */
export async function secureFetch(url: string, options: RequestInit = {}): Promise<Response> {
  let finalUrl = url;
  if (window.location.hostname !== 'localhost' && window.location.hostname !== '127.0.0.1') {
    // En producción, si la URL es relativa y empieza con /api/, anteponer /media-impact
    if (!url.startsWith('http') && url.startsWith('/api/')) {
      finalUrl = `/media-impact${url}`;
    }
  }
  const absoluteUrl = finalUrl.startsWith('http') ? finalUrl : `${API_BASE_URL}${finalUrl}`;
  const headers = new Headers(options.headers || {});

  // Automatically set Content-Type if we have a string body and no explicit header
  if (options.body && typeof options.body === 'string' && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  try {
    const user = auth.currentUser;
    if (user) {
      // Direct, reactively reliable token retrieval from Firebase SDK cache/refresh
      const token = await user.getIdToken();
      headers.set('Authorization', `Bearer ${token}`);
    }
  } catch (err) {
    console.error("Error obtaining Firebase Auth ID Token for secureFetch:", err);
  }

  return fetch(absoluteUrl, {
    ...options,
    headers
  });
}
