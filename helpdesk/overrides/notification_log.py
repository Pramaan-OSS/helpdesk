"""Keep local alerts while automated outbound email awaits loop markers."""
import frappe
from frappe.desk.doctype.notification_log.notification_log import NotificationLog, set_notifications_as_unseen

class PramaanNotificationLog(NotificationLog):
    def after_insert(self):
        frappe.publish_realtime("notification", after_commit=True, user=self.for_user)
        set_notifications_as_unseen(self.for_user)
