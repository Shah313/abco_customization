import frappe
from frappe.utils import flt
from frappe import _

@frappe.whitelist()
def create_production_plan_from_sales_order(sales_order: str):
    """
    Create Production Plan from Sales Order with automatic sub-assembly items
    """
    try:
        # Validate input
        if not sales_order:
            return {"status": "error", "message": "Sales Order parameter is required"}

        if not frappe.db.exists("Sales Order", sales_order):
            return {"status": "error", "message": f"Sales Order {sales_order} does not exist"}

        # Get Sales Order
        so = frappe.get_doc("Sales Order", sales_order)
        
        # Validate Sales Order status
        if so.docstatus != 1:
            return {"status": "error", "message": "Sales Order must be submitted to create Production Plan"}

        # Check for existing Production Plan
        existing_plan = frappe.db.exists("Production Plan", {"sales_order": sales_order})
        if existing_plan:
            return {
                "status": "info", 
                "message": f"Production Plan already exists: {existing_plan}",
                "production_plan": existing_plan
            }

        # Create new Production Plan
        plan = frappe.new_doc("Production Plan")
        plan.company = so.company
        
        # Set sub-assembly configuration
        plan.include_sub_assembly_items = 1
        plan.skip_available_sub_assembly_items = 0
        plan.consolidate_sub_assembly_items = 0
        
        # Add Sales Order reference
        plan.append("sales_orders", {
            "sales_order": so.name,
            "customer": so.customer,
            "grand_total": so.grand_total,
        })

        # Detect correct child table for plan items
        child_fieldname = _get_production_plan_child_table(plan)
        if not child_fieldname:
            return {"status": "error", "message": "Could not find valid child table for Production Plan items"}

        # Process Sales Order items
        valid_items = _add_sales_order_items_to_plan(so, plan, child_fieldname)
        if not valid_items:
            return {"status": "error", "message": "No items with valid active BOMs found"}

        # Save Production Plan
        plan.insert(ignore_permissions=True)
        frappe.db.commit()

        # Create sub-assembly items
        sub_assembly_count = _create_sub_assembly_items(plan.name, child_fieldname)
        
        # Prepare success response
        success_message = f"Production Plan {plan.name} created successfully"
        if sub_assembly_count > 0:
            success_message += f" with {sub_assembly_count} sub-assembly items"
        
        frappe.msgprint(_(success_message))
        
        return {
            "status": "success", 
            "production_plan": plan.name,
            "sub_assembly_count": sub_assembly_count,
            "message": success_message
        }

    except Exception as e:
        frappe.db.rollback()
        error_log = frappe.log_error(
            frappe.get_traceback(), 
            f"Production Plan Creation Failed for SO: {sales_order}"
        )
        return {
            "status": "error", 
            "message": f"Failed to create Production Plan. See Error Log: {error_log.name}"
        }


def _get_production_plan_child_table(plan_doc):
    """Detect the correct child table field name for Production Plan items"""
    for candidate in ["items", "planned_items", "production_plan_items", "po_items"]:
        if plan_doc.meta.get_field(candidate):
            return candidate
    return None


def _add_sales_order_items_to_plan(sales_order, production_plan, child_fieldname):
    """Add Sales Order items to Production Plan with BOM validation"""
    valid_items = 0
    
    for so_item in sales_order.items:
        bom_name = frappe.db.get_value("BOM", {
            "item": so_item.item_code,
            "is_active": 1,
            "docstatus": 1,
        }, order_by="creation desc")  # Get latest BOM

        if bom_name:
            valid_items += 1
            
            # Determine warehouse
            warehouse = _get_warehouse_for_item(so_item, sales_order)
            
            # Add to production plan
            production_plan.append(child_fieldname, {
                "item_code": so_item.item_code,
                "sales_order": sales_order.name,
                "planned_qty": so_item.qty,
                "warehouse": warehouse,
                "bom_no": bom_name,
            })
            
            frappe.msgprint(_(f"BOM found for {so_item.item_code}: {bom_name}"))
        else:
            frappe.msgprint(_(f"No active BOM found for {so_item.item_code}"))
    
    return valid_items


def _get_warehouse_for_item(item, sales_order):
    """Determine the appropriate warehouse for production item"""
    return (
        getattr(item, "set_source_warehouse", None)
        or getattr(item, "warehouse", None)
        or getattr(sales_order, "set_warehouse", None)
        or getattr(sales_order, "warehouse", None)
    )


def _create_sub_assembly_items(production_plan_name, child_fieldname):
    """Create sub-assembly items for the Production Plan"""
    try:
        plan_doc = frappe.get_doc("Production Plan", production_plan_name)
        sub_assembly_count = 0
        
        # Clear existing sub-assembly items
        if hasattr(plan_doc, 'sub_assembly_items'):
            plan_doc.set('sub_assembly_items', [])
        
        # Process each production item for sub-assemblies
        for production_item in getattr(plan_doc, child_fieldname, []):
            if production_item.bom_no:
                sub_assembly_count += _process_bom_for_sub_assemblies(
                    production_item, plan_doc
                )
        
        # Save if sub-assemblies were found
        if sub_assembly_count > 0:
            plan_doc.save(ignore_permissions=True)
            frappe.db.commit()
            frappe.msgprint(_(f"Created {sub_assembly_count} sub-assembly items"))
        
        return sub_assembly_count
        
    except Exception as e:
        frappe.log_error(
            frappe.get_traceback(), 
            f"Sub Assembly Creation Failed for PP: {production_plan_name}"
        )
        frappe.msgprint(_("Failed to create sub-assembly items automatically"))
        return 0


def _process_bom_for_sub_assemblies(production_item, plan_doc):
    """Process BOM to find and add sub-assembly items"""
    sub_assembly_count = 0
    
    try:
        bom = frappe.get_doc("BOM", production_item.bom_no)
        
        for bom_item in bom.items:
            # Check if this item has its own BOM (making it a sub-assembly)
            sub_bom = frappe.db.get_value("BOM", {
                "item": bom_item.item_code,
                "is_active": 1,
                "docstatus": 1
            })
            
            if sub_bom:
                sub_assembly_count += 1
                
                # Calculate quantities
                required_qty = flt(bom_item.qty) * flt(production_item.planned_qty)
                
                # Add to sub-assembly items table
                plan_doc.append("sub_assembly_items", {
                    "production_item": bom_item.item_code,
                    "item_name": bom_item.item_name or bom_item.item_code,
                    "bom_no": sub_bom,
                    "qty": required_qty,
                    "required_qty": required_qty,
                    "stock_qty": required_qty,
                })
                
    except Exception as e:
        frappe.msgprint(_(f"Error processing BOM {production_item.bom_no}: {str(e)}"))
    
    return sub_assembly_count