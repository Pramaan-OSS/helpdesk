import { io } from "socket.io-client";
const socketio_port = (window as any).socketio_port || 9000;

// extend window object
declare global {
  interface Window {
    site_name: string;
  }
}

export function initSocket() {
  let host = window.location.hostname;
  let siteName = window.site_name || host;
  let port = window.location.port ? `:${socketio_port}` : "";
  let protocol = port ? "http" : "https";
  let url = `${protocol}://${host}${port}/${siteName}`;

  const socket = io(url, {
    withCredentials: true,
    reconnectionAttempts: 5,
  });

  return socket;
}

export const socket = initSocket();
