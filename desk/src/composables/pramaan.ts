import { computed } from "vue";
import { useAuthStore } from "@/stores/auth";

export const missingKeyMessage = "Add PRAMAAN_API_KEY to .env";

export function usePramaanAvailability() {
  const auth = useAuthStore();
  return { configured: computed(() => auth.pramaanConfigured), missingKeyMessage };
}

export function actionError(error: any, fallback: string): string {
  const messages = error?.messages;
  const text = Array.isArray(messages) ? [...new Set(messages)].join(" ") : error?.message;
  return typeof text === "string" && text.trim() ? text : fallback;
}
