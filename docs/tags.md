Tags are a special type of form entity, they allow dynamic creation of subforms based on the `key_value` property of another table, for our purposes the tags table.
Each entry in the tags table is a tag group, and can be given a display name, and configure the corresponding subform with a JSON entry.
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