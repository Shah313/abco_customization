// abco_customization/public/js/sales_order_pp_button.js
frappe.ui.form.on("Sales Order", {
  refresh(frm) {
    // Only for submitted SOs
    if (!frm.is_new() && frm.doc.docstatus === 1) {
      frm.add_custom_button(
        __("Production Plan"),
        () => {
          frappe.confirm(
            __(`Are you sure you want to create a Production Plan for Sales Order <b>${frm.doc.name}</b>?`),
            () => {
              frappe.call({
                method: "abco_customization.api.production_plan.create_production_plan_from_sales_order",
                args: { sales_order: frm.doc.name },
                freeze: true,
                freeze_message: __("Creating Production Plan..."),
                callback: (r) => {
                  if (!r.exc && r.message) {
                    const res = r.message;
                    if (res.status === "success") {
                      frappe.msgprint({
                        title: __("Success"),
                        message: __(`✅ Production Plan <b>${res.production_plan}</b> created.`),
                        indicator: "green",
                      });
                      frappe.set_route("Form", "Production Plan", res.production_plan);
                    } else {
                      frappe.msgprint({
                        title: __("Info"),
                        message: __(res.message || "Unable to create Production Plan."),
                        indicator: "orange",
                      });
                    }
                  } else {
                    frappe.msgprint({
                      title: __("Error"),
                      message: __("Failed to create Production Plan. Please check Error Log."),
                      indicator: "red",
                    });
                  }
                },
              });
            }
          );
        },
        __("Create")
      ).addClass("btn-primary");
    }
  },
});
