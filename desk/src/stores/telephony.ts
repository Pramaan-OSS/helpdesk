import { defineStore } from "pinia";
import { createResource } from "frappe-ui";

export const useTelephonyStore = defineStore("telephony", {
  state: () =>
    ({
      isLoading: false,
      isCallingEnabled: false,
      linkDoc: { doctype: "", docname: "" },
      callMethod: (_params: any) => {},
    }) as {
      isLoading: boolean;
      isCallingEnabled: boolean;
      linkDoc: { doctype: string; docname: string };
      callMethod: (params: any) => void;
    },
  actions: {
    setMakeCall(value: (params: any) => void) {
      this.callMethod = value;
    },
    makeCall(params: any) {
      this.callMethod(params);
    },
    setIsCallingEnabled(value: boolean) {
      this.isCallingEnabled = value;
    },
    async fetchCallIntegrationStatus() {
      try {
        const availability = await createResource({
          url: "helpdesk.api.capabilities.availability",
        }).fetch();
        this.setIsCallingEnabled(Boolean(availability?.browser_calling?.enabled));
      } catch {
        this.setIsCallingEnabled(false);
      }
    },
    setLinkDoc(params: any) {
      this.linkDoc = params;
    },
  },
});
