import { computed } from "vue";
import { useAuthStore } from "@/stores/auth";

export const missingKeyMessage = "This needs a Pramaan key. Ask your administrator to set PRAMAAN_API_KEY.";

export function usePramaanAvailability() {
  const auth = useAuthStore();
  return { configured: computed(() => auth.pramaanConfigured), missingKeyMessage };
}

export function actionError(error: any, fallback: string): string {
  const messages = error?.messages;
  const text = Array.isArray(messages) ? [...new Set(messages)].join(" ") : error?.message;
  return typeof text === "string" && text.trim() ? text : fallback;
}
