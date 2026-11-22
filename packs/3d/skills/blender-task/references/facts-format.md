# Facts file for blender_job.py check

Write the facts from the user's request, before looking at the result. A fact taken from the result proves nothing.

```json
{
  "objects": [
    {
      "name": "Table",
      "type": "MESH",
      "dimensions_m": [1.2, 0.6, 0.75],
      "tolerance_m": 0.005,
      "polygons_max": 5000,
      "polygons_min": 12,
      "modifiers": ["BEVEL"],
      "modifiers_none": true,
      "scale_applied": true,
      "materials_min": 1,
      "uv_layers_min": 1,
      "parent": null
    }
  ],
  "absent": ["Cube"],
  "count": { "MESH": 1 },
  "unit_scale": 1.0
}
```

- `dimensions_m` is x, y, z in metres as Blender reports them (Blender is +Z up; glTF export turns that into +Y up). The state file's dimensions are multiplied by the scene's unit scale first.
- Polygon limits use the count after modifiers when the state file has it (`polygons_evaluated`).
- `modifiers` lists modifier types that have to be present; `modifiers_none` says all were applied or removed. Use one or the other.
- Every key is optional. Only what is written is checked, and an empty file is reported as not verified.
