import { defineStore } from "pinia";
export const useTelephonyStore = defineStore("telephony", {
  state: () => ({ isLoading: false, isCallingEnabled: false, linkDoc: { doctype: "", docname: "" }, callMethod: (_params: any) => {} }),
  actions: {
    setMakeCall(value: (params: any) => void) { this.callMethod = value; },
    makeCall(params: any) { this.callMethod(params); },
    setIsCallingEnabled(_value: boolean) { this.isCallingEnabled = false; },
    async fetchCallIntegrationStatus() { this.isCallingEnabled = false; },
    setLinkDoc(params: any) { this.linkDoc = params; },
  },
});
