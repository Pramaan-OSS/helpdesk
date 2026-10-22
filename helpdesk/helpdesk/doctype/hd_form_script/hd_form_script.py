# For license information, please see license.txt

import frappe
import json
import re
from frappe.model.document import Document

from helpdesk.api.settings.field_dependency import (
    get_fields_criteria,
    handle_fields_criteria,
    handle_form_customization,
)


class HDFormScript(Document):
    def before_save(self):
        self.handle_enabled_change()

    def handle_enabled_change(self):
        if self.is_new():
            return
        if not self.is_standard:
            return
        if not self.has_value_changed("enabled"):
            return

        if not self.enabled:
            [_, child_field] = self.get_parent_child_field()
            handle_form_customization(child_field, None, None)

        if self.enabled:
            [parent_field, child_field] = self.get_parent_child_field()
            fields_criteria = get_fields_criteria(self.script)
            handle_fields_criteria(parent_field, child_field, fields_criteria, {})

    def get_parent_child_field(self):
        """Returns the child field from the name of the document"""
        if not self.name:
            return None
        if "Field Dependency" not in self.name:
            return None

        # Assuming the name is in the format "Field Dependency-{parent_field}-{child_field}"
        parts = self.name.split("-")
        if len(parts) < 2:
            return None
        return [parts[1], parts[2]] if len(parts) > 2 else [parts[1], None]

    def on_trash(self):
        if not self.is_standard:
            return
        [_, child_field] = self.get_parent_child_field()
        if not child_field:
            return
        handle_form_customization(child_field, None, None)


def get_form_script(
    dt,
    apply_to="Form",
    is_customer_portal=False,
    apply_on_new_page=False,
):
    """Returns the form script for the given doctype"""
    FormScript = frappe.qb.DocType("HD Form Script")
    audience = FormScript.apply_to_customer_portal == is_customer_portal
    if is_customer_portal and apply_on_new_page:
        audience = audience | ((FormScript.is_standard == 1) & FormScript.name.like("Field Dependency-%"))
    query = (
        frappe.qb.from_(FormScript)
        .select("name", "is_standard", "script")
        .where(FormScript.dt == dt)
        .where(FormScript.apply_to == apply_to)
        .where(FormScript.enabled == 1)
        .where(FormScript.apply_on_new_page == apply_on_new_page)
        .where(audience)
    )

    doc = query.run(as_dict=True)
    if doc:
        result = []
        for row in doc:
            match = re.fullmatch(r"Field Dependency-([a-zA-Z_][a-zA-Z0-9_]*)-([a-zA-Z_][a-zA-Z0-9_]*)", row.name)
            if row.is_standard and match:
                try:
                    mapping = json.loads(row.script.split("//JSON: ")[-1])
                    if isinstance(mapping, str):
                        mapping = json.loads(mapping)
                except (ValueError, AttributeError):
                    continue
                if not isinstance(mapping, dict) or any(not isinstance(key, str) or not isinstance(values, list) or any(not isinstance(value, str) for value in values) for key, values in mapping.items()):
                    continue
                result.append({"kind": "field_dependency", "parent": match[1], "child": match[2], "mapping": mapping})
            else:
                result.append(row.script)
        return result
        # if len(doc) > 1 else doc[0].script
    else:
        return None
