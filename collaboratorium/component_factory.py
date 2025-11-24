from dash import html, dcc, Input, Output, State, ctx, ALL, no_update, MATCH
from datetime import datetime
from visual_customization import dcl
from db import get_dropdown_options


# ==============================================================
# COMPONENT FACTORY
# ==============================================================


def component_for_element(element_config, form_name, value=None):
    """Map element type from YAML to Dash component"""
    element_type = element_config.get("type")
    label = element_config.get("label", element_config["element_id"])
    appearance = element_config.get("appearance", None)

    input_type_mapping = {
        "integer": "number",
        "decimal": "number",
        "email": "email",
        "url": "url",
        "tel": "tel",
        "hidden": "hidden",
    }
    # --- TEXT / NUMBER / DATE ---
    if element_type in ("text", "string", "integer", "decimal", "email", "url", "tel"):
        if appearance == "multiline":
            return html.Div(
                [
                    html.Label(label),
                    dcl.Textarea(
                        id={"type": "input", "form": form_name, "element": element_config["element_id"]},
                        style={'width': '100%'},
                        value=value or "",
                    ),
                ]
            )
        return html.Div(
            [
                html.Label(label),
                dcc.Input(
                    id={"type": "input", "form": form_name, "element": element_config["element_id"]},
                    type=input_type_mapping.get(element_type, "text"),
                    value=value or "",
                    style={'width': '100%'},
                ),
            ]
        )
    
    # --- hidden ---
    elif element_type == "hidden":
        return dcc.Input(
                    id={"type": "input", "form": form_name, "element": element_config["element_id"]},
                    type="hidden",
                    value=value or "",
                )

    # --- datetime ---
    elif element_type == "datetime":
        return html.Div(
            [
                html.Label(label),
                dcc.DatePickerSingle(
                    id={"type": "input", "form": form_name, "element": element_config["element_id"]},
                    date=value or None,
                ),
            ]
        )
    
    # --- boolean ---
    elif element_type == "boolean":
        # Checklist expects a list for `value` — populate accordingly
        checklist_value = [True] if value else []
        return dcc.Checklist(
            id={"type": "input", "form": form_name, "element": element_config["element_id"]},
            options=[{"label": "True", "value": True}],
            value=checklist_value
        )

    # --- SELECT SINGLE ---
    elif element_type == "select_one":
        options = get_dropdown_options(
            element_config["parameters"]["source_table"],
            element_config["parameters"]["value_column"],
            element_config["parameters"]["label_column"],
        )
        return html.Div(
            [
                html.Label(label),
                dcc.Dropdown(
                    id={"type": "input", "form": form_name, "element": element_config["element_id"]},
                    options=options,
                    value=value,
                    clearable=True,
                ),
            ]
        )

    # --- SELECT MULTIPLE ---
    elif element_type == "select_multiple":
        options = get_dropdown_options(
            element_config["parameters"]["source_table"],
            element_config["parameters"]["value_column"],
            element_config["parameters"]["label_column"],
        )
        return html.Div(
            [
                html.Label(label),
                dcc.Dropdown(
                    id={"type": "input", "form": form_name, "element": element_config["element_id"]},
                    options=options,
                    value=value or [],
                    multi=True,
                    clearable=True,
                ),
            ]
        )

    # --- DEFAULT FALLBACK ---
    return html.Div([html.Label(label), html.Div("Unsupported element type")])
