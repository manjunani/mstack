"""Write the facts of the open Blender scene to a JSON state file.

This file runs INSIDE Blender, after the job script:
  blender --background [file.blend] --python job.py --python state_dump.py -- --mstack-state out.json

It reads the scene and writes one new file. It changes nothing in the scene and saves no .blend.
scripts/blender_job.py passes it automatically; you do not call it by hand.
"""
import json
import sys

import bpy

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
if "--mstack-state" not in argv:
    raise SystemExit("state_dump.py: pass -- --mstack-state <file>")
target = argv[argv.index("--mstack-state") + 1]

scene = bpy.context.scene
depsgraph = bpy.context.evaluated_depsgraph_get()
objects = []
for obj in scene.objects:
    entry = {
        "name": obj.name,
        "type": obj.type,
        "dimensions": [round(v, 6) for v in obj.dimensions],
        "scale": [round(v, 6) for v in obj.scale],
        "location": [round(v, 6) for v in obj.location],
        "rotation_euler": [round(v, 6) for v in obj.rotation_euler],
        "parent": obj.parent.name if obj.parent else None,
        "modifiers": [{"name": m.name, "type": m.type} for m in obj.modifiers],
        "materials": [slot.material.name for slot in obj.material_slots if slot.material],
        "hide_render": bool(obj.hide_render),
    }
    if obj.type == "MESH":
        mesh = obj.data
        entry["polygons"] = len(mesh.polygons)
        entry["vertices"] = len(mesh.vertices)
        entry["uv_layers"] = len(mesh.uv_layers)
        evaluated = obj.evaluated_get(depsgraph)
        final = evaluated.to_mesh()
        final.calc_loop_triangles()
        entry["polygons_evaluated"] = len(final.polygons)
        entry["triangles_evaluated"] = len(final.loop_triangles)
        evaluated.to_mesh_clear()
    objects.append(entry)

state = {
    "tool": "mstack blender-task state dump",
    "blender_version": bpy.app.version_string,
    "file": bpy.data.filepath or None,
    "scene": scene.name,
    "unit_system": scene.unit_settings.system,
    "unit_scale": scene.unit_settings.scale_length,
    "frame": scene.frame_current,
    "objects": objects,
}
with open(target, "x", encoding="utf-8") as handle:
    json.dump(state, handle, indent=2)
print(f"mstack state: {len(objects)} objects written to {target}")
