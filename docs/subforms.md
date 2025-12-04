Subforms are a special type of form entity that allow more complex data to be stored as JSON in one table column. They can be defined statically in the config.yaml, but they can also be dynamically created based on the `key_value` property of another table.

## Static Subforms
In the parameters, you can create multiple groups of forms. These cannot be named `source_table`, `value_column`, and `label_column` otherwise it will be interpreted as a dynamic subform.
This group id can be an arbitrary string.
Inside, define elements as normal.

```yaml
      description:
        type: subform
        label: Description
        parameters:
          '1':
            description:
              type: string
              label: Summary (optional)
              appearance: multiline
            attachments:
              type: string
              label: Attachments
```

## Dynamic Subforms
Configuration of the table to pull configuration options from. The parameters are configured the same as would be done for a dropdown.
```yaml
      tag_groups:
        type: subform
        label: Tag Groups
        parameters:
          source_table: tag_groups
          value_column: id
          label_column: name
```


Each entry in the tag_groups table is a tag group, and can be given a display name, and configure the corresponding subform with a JSON entry.
These JSON entries follow the same object structure as other entities, inspired by ODK. See these examples.

```json
{
  "time_spent": {
    "type": "decimal", 
    "label": "Time Spent"
  }
}
```

```json
{
  "work_area": {
    "type": "select_multiple", 
    "label": "Work Area",
    "appearance": "dropdown", 
    "list_name": "work_area_list", 
    "work_area_list":
      {
        "agroecology": "Agroecology",
        "saas": "SaaS",
        ...
      }
  }
}
```
Or an example of having multiple tags in a tag group. This example isn't directly relavant, we'd likely split the different stages into their own initiatives.
```json
{
  "stage": {
    "type": "select_multiple", 
    "label": "Work Stage",
    "appearance": "dropdown", 
    "list_name": "work_stage_list", 
    "work_stage_list":
      {
        "ideation": "Ideation",
        "pitching": "Pitching",
        "preprod": "PreProduction",
        "internal": "Internal Testing",
        "marketing": "Marketing",
        "delivery": "Delivery",
      }
  },
  "ideation_time": {
    "type": "decimal", 
    "label": "Time Spent: Ideation"
  },
  "pitching_time": {
    "type": "decimal", 
    "label": "Time Spent: Pitching"
  },
    "preprod_time": {
    "type": "decimal", 
    "label": "Time Spent: PreProduction"
  },
    "internal_time": {
    "type": "decimal", 
    "label": "Time Spent: Internal Testing"
  },
    "marketing_time": {
    "type": "decimal", 
    "label": "Time Spent: Marketing"
  },
    "delivery_time": {
    "type": "decimal", 
    "label": "Time Spent: Delivery"
  },
}
```