import { call } from "frappe-ui";
import type { RouteLocationNormalized, RouteLocationRaw } from "vue-router";

const PERSONA_DONE_KEY = "helpdesk_persona_captured";

let personaChecked = false;

// Minimal auth contract, so this module doesn't import the auth store (cycle).
interface PersonaAuth {
  isLoggedIn: boolean;
  hasDeskAccess: boolean;
  isAdmin: boolean;
  personaCaptured: boolean;
}

function isPersonaCaptured(auth: PersonaAuth): boolean {
  try {
    if (localStorage.getItem(PERSONA_DONE_KEY)) return true;
  } catch {
    // storage blocked — fall through to the server flag
  }
  return !!auth.personaCaptured;
}

// Gate for the route's beforeEnter: only an uncaptured desk admin may view
// the wizard, even via URL.
export function canViewPersona(auth: PersonaAuth): boolean {
  return (
    auth.isLoggedIn &&
    auth.hasDeskAccess &&
    auth.isAdmin &&
    !isPersonaCaptured(auth)
  );
}

// Interrupt the first eligible admin navigation, once per session. Returns
// where to redirect, or undefined to continue.
export function personaInterrupt(
  to: RouteLocationNormalized,
  auth: PersonaAuth
): RouteLocationRaw | undefined {
  if (to.name === "Persona" || personaChecked) return;
  if (!(auth.isLoggedIn && auth.hasDeskAccess && auth.isAdmin)) return;
  personaChecked = true;
  if (canViewPersona(auth)) return { name: "Persona", query: { returnTo: to.fullPath } };
}

export async function markPersonaCaptured(brandName?: string): Promise<void> {
  try { localStorage.setItem(PERSONA_DONE_KEY, "1"); } catch { /* Server flag still persists the choice. */ }
  await call("helpdesk.api.onboarding.mark_persona_captured", {
    brand_name: brandName,
  });
}
