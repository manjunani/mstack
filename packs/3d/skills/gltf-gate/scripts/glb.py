#!/usr/bin/env python3
"""Read a glTF 2.0 model (.glb container or .gltf JSON) with the standard library only.

  glb.py <file>          print what the file holds and any structural errors
  glb.py <file> --json   the same as one JSON object

Other scripts import this file as a module. It is the single reader they share:
  sniff(path)            what kind of file this really is (glb, gltf, html, zip, empty ...)
  load(path)             parse the container and the JSON; collect errors, never raise on bad data
  structure(model)       check required fields and that every index and byte range exists
  stats(model)           triangles, meshes, materials, textures, animations, bounding box in metres
  read_accessor(m, i)    the values of one accessor as a list
  check_budget(s, p)     compare stats with one budget profile

Exit codes: 0 = readable and no structural error, 1 = structural errors, 2 = not a model file or unreadable.
This script only reads. It never changes the model.
"""
import argparse
import base64
import json
import math
import pathlib
import struct
import sys

GLB_MAGIC = 0x46546C67
CHUNK_JSON = 0x4E4F534A
CHUNK_BIN = 0x004E4942
COMPONENT = {5120: ("b", 1), 5121: ("B", 1), 5122: ("h", 2), 5123: ("H", 2), 5125: ("I", 4), 5126: ("f", 4)}
NORMALIZE = {5120: 127.0, 5121: 255.0, 5122: 32767.0, 5123: 65535.0}
TYPE_COUNT = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT2": 4, "MAT3": 9, "MAT4": 16}
IDENTITY = [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0]


class Model:
    """A parsed file. `doc` is the glTF JSON, `buffers` the bytes of each buffer (None when missing)."""

    def __init__(self, path):
        self.path = pathlib.Path(path)
        self.kind = "unknown"
        self.doc = {}
        self.buffers = []
        self.errors = []
        self.warnings = []
        self.file_size = 0
        self.readable = False


def sniff(path):
    """Return (kind, detail). kind is one of: missing, empty, glb, gltf, json, html, zip, fbx, unknown."""
    path = pathlib.Path(path)
    if not path.is_file():
        return "missing", "no such file"
    size = path.stat().st_size
    if size == 0:
        return "empty", "0 bytes"
    with path.open("rb") as handle:
        head = handle.read(4096)
    if head[:4] == b"glTF":
        return "glb", "binary glTF container"
    if head[:4] == b"PK\x03\x04":
        return "zip", "a zip archive (USDZ files are zip archives)"
    if head[:18] == b"Kaydara FBX Binary":
        return "fbx", "an FBX file"
    text = head.lstrip(b"\xef\xbb\xbf \t\r\n")
    if text[:1] == b"<":
        return "html", "starts with markup; probably a web page or error page saved under a model name"
    if text[:1] == b"{":
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, UnicodeDecodeError):
            return "json", "starts like JSON but does not parse"
        if isinstance(doc, dict) and "asset" in doc:
            return "gltf", "glTF JSON"
        return "json", "JSON without a glTF 'asset' field; probably an API reply saved under a model name"
    return "unknown", "no known model signature in the first bytes"


def _load_glb(model, data):
    if len(data) < 12:
        model.errors.append(f"file is {len(data)} bytes; a GLB header alone is 12")
        return
    magic, version, length = struct.unpack_from("<III", data, 0)
    if magic != GLB_MAGIC:
        model.errors.append("first four bytes are not 'glTF'")
        return
    if version != 2:
        model.errors.append(f"container version is {version}; only version 2 is read")
    if length != len(data):
        model.errors.append(f"header says the file is {length} bytes, but it is {len(data)}")
    offset, index, json_bytes, bin_bytes = 12, 0, None, None
    while offset + 8 <= len(data):
        chunk_length, chunk_type = struct.unpack_from("<II", data, offset)
        start = offset + 8
        label = {CHUNK_JSON: "JSON", CHUNK_BIN: "BIN"}.get(chunk_type, f"type 0x{chunk_type:08x}")
        if start + chunk_length > len(data):
            model.errors.append(f"chunk {index} ({label}) claims {chunk_length} bytes, only {len(data) - start} remain")
            break
        if chunk_length % 4:
            model.errors.append(f"chunk {index} ({label}) length {chunk_length} is not a multiple of 4")
        if index == 0 and chunk_type != CHUNK_JSON:
            model.errors.append(f"first chunk is {label}; it has to be JSON")
        if chunk_type == CHUNK_JSON and json_bytes is None:
            json_bytes = data[start:start + chunk_length]
        elif chunk_type == CHUNK_BIN and bin_bytes is None:
            bin_bytes = data[start:start + chunk_length]
        offset = start + chunk_length
        index += 1
    if offset < len(data) and not model.errors:
        model.warnings.append(f"{len(data) - offset} stray bytes after the last chunk")
    if json_bytes is None:
        model.errors.append("no JSON chunk could be read")
        return
    try:
        doc = json.loads(json_bytes.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        model.errors.append(f"JSON chunk does not parse: {exc}")
        return
    if not isinstance(doc, dict):
        model.errors.append("JSON chunk is not an object")
        return
    model.doc = doc
    model.readable = True
    for i, buffer in enumerate(doc.get("buffers", []) if isinstance(doc.get("buffers"), list) else []):
        if isinstance(buffer, dict) and "uri" not in buffer and i == 0:
            if bin_bytes is None:
                model.errors.append("buffer 0 has no uri and the file has no BIN chunk")
            model.buffers.append(bin_bytes)
        else:
            model.buffers.append(_load_uri(model, buffer.get("uri") if isinstance(buffer, dict) else None, f"buffer {i}"))


def _load_uri(model, uri, what):
    if not isinstance(uri, str) or not uri:
        model.errors.append(f"{what} has no data: no uri")
        return None
    if uri.startswith("data:"):
        head, _, payload = uri.partition(",")
        try:
            return base64.b64decode(payload, validate=False) if ";base64" in head else payload.encode("utf-8")
        except ValueError:
            model.errors.append(f"{what}: the data URI does not decode")
            return None
    if "://" in uri:
        model.warnings.append(f"{what} points to a network address ({uri[:60]}); it was not fetched")
        return None
    base = model.path.parent.resolve()
    target = (base / uri).resolve()
    if base != target and base not in target.parents:
        model.warnings.append(f"{what} points outside the model's folder ({uri}); it was not read")
        return None
    if not target.is_file():
        model.errors.append(f"{what}: file '{uri}' is missing")
        return None
    return target.read_bytes()


def load(path):
    """Parse a .glb or .gltf file. Problems are collected in model.errors; this function does not raise on bad data."""
    model = Model(path)
    kind, detail = sniff(path)
    model.kind = kind
    if kind in ("missing", "empty", "html", "zip", "fbx", "json", "unknown"):
        model.errors.append(f"not a glTF model: {detail}")
        return model
    data = model.path.read_bytes()
    model.file_size = len(data)
    if kind == "glb":
        _load_glb(model, data)
        return model
    try:
        doc = json.loads(data.decode("utf-8-sig"))
    except (ValueError, UnicodeDecodeError) as exc:
        model.errors.append(f"JSON does not parse: {exc}")
        return model
    model.doc = doc
    model.readable = True
    for i, buffer in enumerate(doc.get("buffers", []) if isinstance(doc.get("buffers"), list) else []):
        model.buffers.append(_load_uri(model, buffer.get("uri") if isinstance(buffer, dict) else None, f"buffer {i}"))
    return model


def _items(doc, key):
    value = doc.get(key, [])
    return value if isinstance(value, list) else []


def _is_index(value, array):
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value < len(array)


def structure(model):
    """Check required fields, index references and byte ranges. Adds to model.errors and returns that list."""
    if not model.readable:
        return model.errors
    doc, err = model.doc, model.errors
    asset = doc.get("asset")
    if not isinstance(asset, dict) or "version" not in asset:
        err.append("required field asset.version is missing")
    elif not str(asset["version"]).startswith("2"):
        err.append(f"asset.version is {asset['version']}; this reader handles 2.x")
    buffers, views, accessors = _items(doc, "buffers"), _items(doc, "bufferViews"), _items(doc, "accessors")
    meshes, nodes, materials = _items(doc, "meshes"), _items(doc, "nodes"), _items(doc, "materials")
    textures, images, skins = _items(doc, "textures"), _items(doc, "images"), _items(doc, "skins")

    for i, buffer in enumerate(buffers):
        if not isinstance(buffer, dict) or not isinstance(buffer.get("byteLength"), int):
            err.append(f"buffer {i}: required field byteLength is missing")
            continue
        data = model.buffers[i] if i < len(model.buffers) else None
        if data is not None and buffer["byteLength"] > len(data):
            err.append(f"buffer {i}: declares {buffer['byteLength']} bytes, the data holds {len(data)}")
    for i, view in enumerate(views):
        if not isinstance(view, dict) or not isinstance(view.get("byteLength"), int) or "buffer" not in view:
            err.append(f"bufferView {i}: required fields buffer and byteLength")
            continue
        if not _is_index(view["buffer"], buffers):
            err.append(f"bufferView {i}: buffer {view['buffer']} does not exist")
            continue
        declared = buffers[view["buffer"]].get("byteLength") if isinstance(buffers[view["buffer"]], dict) else None
        end = view.get("byteOffset", 0) + view["byteLength"]
        if isinstance(declared, int) and end > declared:
            err.append(f"bufferView {i}: ends at byte {end}, buffer {view['buffer']} has {declared}")
    for i, acc in enumerate(accessors):
        if not isinstance(acc, dict):
            err.append(f"accessor {i}: not an object")
            continue
        missing = [k for k in ("componentType", "count", "type") if k not in acc]
        if missing:
            err.append(f"accessor {i}: required field {', '.join(missing)} is missing")
            continue
        if acc["componentType"] not in COMPONENT or acc["type"] not in TYPE_COUNT:
            err.append(f"accessor {i}: unknown componentType {acc['componentType']} or type {acc['type']}")
            continue
        if not isinstance(acc["count"], int) or acc["count"] < 1:
            err.append(f"accessor {i}: count is {acc['count']}; it has to be 1 or more")
            continue
        if "bufferView" not in acc:
            continue  # sparse, or filled in by a compression extension
        if not _is_index(acc["bufferView"], views):
            err.append(f"accessor {i}: bufferView {acc['bufferView']} does not exist")
            continue
        view = views[acc["bufferView"]]
        if not isinstance(view, dict) or not isinstance(view.get("byteLength"), int):
            continue
        element = COMPONENT[acc["componentType"]][1] * TYPE_COUNT[acc["type"]]
        stride = view.get("byteStride") or element
        needed = acc.get("byteOffset", 0) + stride * (acc["count"] - 1) + element
        if needed > view["byteLength"]:
            err.append(f"accessor {i}: needs {needed} bytes, bufferView {acc['bufferView']} holds {view['byteLength']}")

    def ref(value, array, where, what):
        if value is not None and not _is_index(value, array):
            err.append(f"{where}: {what} {value} does not exist")

    for i, mesh in enumerate(meshes):
        prims = mesh.get("primitives") if isinstance(mesh, dict) else None
        if not isinstance(prims, list) or not prims:
            err.append(f"mesh {i}: required field primitives is missing or empty")
            continue
        for j, prim in enumerate(prims):
            where = f"mesh {i} primitive {j}"
            attrs = prim.get("attributes") if isinstance(prim, dict) else None
            if not isinstance(attrs, dict) or not attrs:
                err.append(f"{where}: required field attributes is missing")
                continue
            for name, index in attrs.items():
                ref(index, accessors, where, f"attribute {name} accessor")
            ref(prim.get("indices"), accessors, where, "indices accessor")
            ref(prim.get("material"), materials, where, "material")
            compressed = isinstance(prim.get("extensions"), dict) and prim["extensions"]
            if "POSITION" not in attrs:
                model.warnings.append(f"{where}: no POSITION attribute; nothing will be drawn")
            elif _is_index(attrs["POSITION"], accessors) and isinstance(accessors[attrs["POSITION"]], dict):
                pos = accessors[attrs["POSITION"]]
                if not (isinstance(pos.get("min"), list) and isinstance(pos.get("max"), list)) and not compressed:
                    err.append(f"{where}: POSITION accessor {attrs['POSITION']} has no min and max")
    for i, node in enumerate(nodes):
        if not isinstance(node, dict):
            err.append(f"node {i}: not an object")
            continue
        ref(node.get("mesh"), meshes, f"node {i}", "mesh")
        ref(node.get("skin"), skins, f"node {i}", "skin")
        for child in node.get("children", []) if isinstance(node.get("children"), list) else []:
            ref(child, nodes, f"node {i}", "child node")
    for i, scene in enumerate(_items(doc, "scenes")):
        for root in scene.get("nodes", []) if isinstance(scene, dict) else []:
            ref(root, nodes, f"scene {i}", "node")
    if "scene" in doc:
        ref(doc["scene"], _items(doc, "scenes"), "default scene", "scene")
    for i, texture in enumerate(textures):
        if isinstance(texture, dict):
            ref(texture.get("source"), images, f"texture {i}", "image")
    for i, image in enumerate(images):
        if isinstance(image, dict):
            ref(image.get("bufferView"), views, f"image {i}", "bufferView")
            if "uri" not in image and "bufferView" not in image:
                err.append(f"image {i}: neither uri nor bufferView")
    for i, skin in enumerate(skins):
        joints = skin.get("joints") if isinstance(skin, dict) else None
        if not isinstance(joints, list) or not joints:
            err.append(f"skin {i}: required field joints is missing or empty")
            continue
        for joint in joints:
            ref(joint, nodes, f"skin {i}", "joint node")
        ref(skin.get("inverseBindMatrices"), accessors, f"skin {i}", "inverseBindMatrices accessor")
        ibm = skin.get("inverseBindMatrices")
        if _is_index(ibm, accessors) and isinstance(accessors[ibm], dict) and accessors[ibm].get("count") != len(joints):
            err.append(f"skin {i}: {len(joints)} joints but {accessors[ibm].get('count')} inverse bind matrices")
    for i, anim in enumerate(_items(doc, "animations")):
        samplers = anim.get("samplers") if isinstance(anim, dict) else None
        channels = anim.get("channels") if isinstance(anim, dict) else None
        if not isinstance(samplers, list) or not isinstance(channels, list) or not channels:
            err.append(f"animation {i}: required fields channels and samplers")
            continue
        for j, sampler in enumerate(samplers):
            if not isinstance(sampler, dict) or "input" not in sampler or "output" not in sampler:
                err.append(f"animation {i} sampler {j}: required fields input and output")
                continue
            ref(sampler["input"], accessors, f"animation {i} sampler {j}", "input accessor")
            ref(sampler["output"], accessors, f"animation {i} sampler {j}", "output accessor")
        for j, channel in enumerate(channels):
            target = channel.get("target") if isinstance(channel, dict) else None
            if not isinstance(target, dict) or "path" not in target or "sampler" not in channel:
                err.append(f"animation {i} channel {j}: required fields sampler and target.path")
                continue
            ref(channel["sampler"], samplers, f"animation {i} channel {j}", "sampler")
            ref(target.get("node"), nodes, f"animation {i} channel {j}", "target node")
    return err


def read_accessor(model, index):
    """Return the accessor's values: a list of numbers for SCALAR, a list of tuples otherwise. Raises ValueError."""
    accessors, views = _items(model.doc, "accessors"), _items(model.doc, "bufferViews")
    if not _is_index(index, accessors):
        raise ValueError(f"accessor {index} does not exist")
    acc = accessors[index]
    if "sparse" in acc:
        raise ValueError(f"accessor {index} is sparse; this reader does not expand sparse data")
    if not _is_index(acc.get("bufferView"), views):
        raise ValueError(f"accessor {index} has no readable bufferView (compressed or missing)")
    view = views[acc["bufferView"]]
    data = model.buffers[view["buffer"]] if _is_index(view.get("buffer"), model.buffers) else None
    if data is None:
        raise ValueError(f"accessor {index}: the buffer data is not available")
    code, size = COMPONENT[acc["componentType"]]
    n = TYPE_COUNT[acc["type"]]
    stride = view.get("byteStride") or size * n
    start = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
    if start + stride * (acc["count"] - 1) + size * n > len(data):
        raise ValueError(f"accessor {index} reads past the end of its buffer")
    fmt = "<" + code * n
    scale = NORMALIZE.get(acc["componentType"]) if acc.get("normalized") else None
    out = []
    for k in range(acc["count"]):
        values = struct.unpack_from(fmt, data, start + k * stride)
        if scale:
            values = tuple(max(v / scale, -1.0) for v in values)
        out.append(values[0] if n == 1 else values)
    return out


def mat_mul(a, b):
    """Column-major 4x4 product a * b."""
    return [sum(a[k * 4 + r] * b[c * 4 + k] for k in range(4)) for c in range(4) for r in range(4)]


def trs_matrix(t, q, s):
    x, y, z, w = q
    length = math.sqrt(x * x + y * y + z * z + w * w) or 1.0
    x, y, z, w = x / length, y / length, z / length, w / length
    return [
        (1 - 2 * (y * y + z * z)) * s[0], (2 * (x * y + z * w)) * s[0], (2 * (x * z - y * w)) * s[0], 0.0,
        (2 * (x * y - z * w)) * s[1], (1 - 2 * (x * x + z * z)) * s[1], (2 * (y * z + x * w)) * s[1], 0.0,
        (2 * (x * z + y * w)) * s[2], (2 * (y * z - x * w)) * s[2], (1 - 2 * (x * x + y * y)) * s[2], 0.0,
        t[0], t[1], t[2], 1.0,
    ]


def node_trs(node):
    return (list(node.get("translation", [0.0, 0.0, 0.0])), list(node.get("rotation", [0.0, 0.0, 0.0, 1.0])),
            list(node.get("scale", [1.0, 1.0, 1.0])))


def node_matrix(node):
    matrix = node.get("matrix")
    if isinstance(matrix, list) and len(matrix) == 16:
        return [float(v) for v in matrix]
    return trs_matrix(*node_trs(node))


def transform_point(m, p):
    return (m[0] * p[0] + m[4] * p[1] + m[8] * p[2] + m[12],
            m[1] * p[0] + m[5] * p[1] + m[9] * p[2] + m[13],
            m[2] * p[0] + m[6] * p[1] + m[10] * p[2] + m[14])


def scene_roots(doc):
    nodes, scenes = _items(doc, "nodes"), _items(doc, "scenes")
    if scenes:
        index = doc.get("scene", 0)
        scene = scenes[index] if _is_index(index, scenes) else scenes[0]
        return [n for n in scene.get("nodes", []) if _is_index(n, nodes)] if isinstance(scene, dict) else []
    children = {c for node in nodes if isinstance(node, dict) for c in node.get("children", []) if isinstance(c, int)}
    return [i for i in range(len(nodes)) if i not in children]


def walk(doc):
    """Yield (node index, world matrix) for every node reachable from the default scene. Cycles are cut."""
    nodes = _items(doc, "nodes")
    stack = [(root, IDENTITY, frozenset()) for root in reversed(scene_roots(doc))]
    while stack:
        index, parent, seen = stack.pop()
        if index in seen or not _is_index(index, nodes) or not isinstance(nodes[index], dict):
            continue
        world = mat_mul(parent, node_matrix(nodes[index]))
        yield index, world
        for child in reversed(nodes[index].get("children", []) or []):
            stack.append((child, world, seen | {index}))


def _primitive_triangles(prim, accessors):
    attrs = prim.get("attributes", {}) if isinstance(prim, dict) else {}
    source = prim.get("indices", attrs.get("POSITION")) if isinstance(prim, dict) else None
    if not _is_index(source, accessors) or not isinstance(accessors[source].get("count"), int):
        return 0, 0
    count, mode = accessors[source]["count"], prim.get("mode", 4)
    position = attrs.get("POSITION")
    vertices = accessors[position].get("count", 0) if _is_index(position, accessors) else 0
    if mode == 4:
        return count // 3, vertices
    if mode in (5, 6):
        return max(count - 2, 0), vertices
    return 0, vertices


def image_size(data):
    """Return (format, width, height) from the first bytes of an image, or (format, None, None)."""
    if data is None or len(data) < 24:
        return "unknown", None, None
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        width, height = struct.unpack_from(">II", data, 16)
        return "png", width, height
    if data[:2] == b"\xff\xd8":
        pos = 2
        while pos + 9 < len(data):
            if data[pos] != 0xFF:
                pos += 1
                continue
            marker = data[pos + 1]
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                pos += 2
                continue
            length = struct.unpack_from(">H", data, pos + 2)[0]
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                height, width = struct.unpack_from(">HH", data, pos + 5)
                return "jpeg", width, height
            pos += 2 + length
        return "jpeg", None, None
    if data[:12] == b"\xabKTX 20\xbb\r\n\x1a\n" and len(data) >= 28:
        width, height = struct.unpack_from("<II", data, 20)
        return "ktx2", width, height
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP" and len(data) >= 30:
        tag = data[12:16]
        if tag == b"VP8X":
            width = 1 + int.from_bytes(data[24:27], "little")
            height = 1 + int.from_bytes(data[27:30], "little")
            return "webp", width, height
        if tag == b"VP8L":
            bits = int.from_bytes(data[21:25], "little")
            return "webp", (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
        if tag == b"VP8 ":
            width, height = struct.unpack_from("<HH", data, 26)
            return "webp", width & 0x3FFF, height & 0x3FFF
        return "webp", None, None
    return "unknown", None, None


def _image_bytes(model, image):
    views = _items(model.doc, "bufferViews")
    if _is_index(image.get("bufferView"), views):
        view = views[image["bufferView"]]
        data = model.buffers[view["buffer"]] if _is_index(view.get("buffer"), model.buffers) else None
        if data is None or not isinstance(view.get("byteLength"), int):
            return None
        start = view.get("byteOffset", 0)
        return data[start:start + view["byteLength"]]
    uri = image.get("uri")
    if isinstance(uri, str) and uri.startswith("data:"):
        try:
            return base64.b64decode(uri.partition(",")[2], validate=False)
        except ValueError:
            return None
    if isinstance(uri, str) and "://" not in uri:
        base = model.path.parent.resolve()
        target = (base / uri).resolve()
        if (base == target or base in target.parents) and target.is_file():
            return target.read_bytes()
    return None


def stats(model):
    """Count what the file holds. Triangle and draw-call counts follow the default scene, so reused meshes count each time."""
    doc = model.doc
    accessors, meshes, nodes = _items(doc, "accessors"), _items(doc, "meshes"), _items(doc, "nodes")
    per_mesh = []
    for mesh in meshes:
        prims = mesh.get("primitives", []) if isinstance(mesh, dict) else []
        counted = [_primitive_triangles(p, accessors) for p in prims if isinstance(p, dict)]
        per_mesh.append({"primitives": len(counted), "triangles": sum(c[0] for c in counted), "vertices": sum(c[1] for c in counted)})

    triangles = draws = vertices = 0
    low, high = [math.inf] * 3, [-math.inf] * 3
    skinned = unbounded = 0
    for index, world in walk(doc):
        node = nodes[index]
        if not _is_index(node.get("mesh"), meshes):
            continue
        entry = per_mesh[node["mesh"]]
        triangles += entry["triangles"]
        draws += entry["primitives"]
        vertices += entry["vertices"]
        matrix = world
        if "skin" in node:
            skinned += 1
            matrix = IDENTITY  # the node's own transform does not apply to a skinned mesh
        for prim in meshes[node["mesh"]].get("primitives", []):
            position = prim.get("attributes", {}).get("POSITION") if isinstance(prim, dict) else None
            acc = accessors[position] if _is_index(position, accessors) else {}
            lo, hi = acc.get("min"), acc.get("max")
            if not (isinstance(lo, list) and isinstance(hi, list) and len(lo) == 3 and len(hi) == 3):
                unbounded += 1
                continue
            for corner in range(8):
                point = transform_point(matrix, [hi[a] if corner >> a & 1 else lo[a] for a in range(3)])
                for a in range(3):
                    low[a] = min(low[a], point[a])
                    high[a] = max(high[a], point[a])
    bounds = None
    if low[0] != math.inf:
        bounds = {"min": [round(v, 6) for v in low], "max": [round(v, 6) for v in high],
                  "size": [round(high[a] - low[a], 6) for a in range(3)],
                  "centre": [round((high[a] + low[a]) / 2, 6) for a in range(3)]}

    images, memory, memory_known = [], 0, True
    for i, image in enumerate(_items(doc, "images")):
        data = _image_bytes(model, image) if isinstance(image, dict) else None
        kind, width, height = image_size(data)
        images.append({"index": i, "format": kind, "width": width, "height": height,
                       "bytes": len(data) if data is not None else None})
        if width and height and kind != "ktx2":
            memory += width * height * 4 * 4 // 3
        else:
            memory_known = False
    animations = []
    for i, anim in enumerate(_items(doc, "animations")):
        duration = 0.0
        for sampler in anim.get("samplers", []) if isinstance(anim, dict) else []:
            acc = accessors[sampler["input"]] if isinstance(sampler, dict) and _is_index(sampler.get("input"), accessors) else {}
            if isinstance(acc.get("max"), list) and acc["max"]:
                duration = max(duration, float(acc["max"][0]))
        animations.append({"index": i, "name": anim.get("name", f"animation {i}") if isinstance(anim, dict) else "",
                           "channels": len(anim.get("channels", [])) if isinstance(anim, dict) else 0,
                           "duration_s": round(duration, 4)})
    sizes = [max(i["width"] or 0, i["height"] or 0) for i in images]
    return {
        "file": str(model.path), "kind": model.kind, "file_size_bytes": model.file_size,
        "generator": doc.get("asset", {}).get("generator") if isinstance(doc.get("asset"), dict) else None,
        "meshes": len(meshes), "meshes_unique_triangles": sum(m["triangles"] for m in per_mesh),
        "triangles_in_scene": triangles, "vertices_in_scene": vertices, "draw_calls_in_scene": draws,
        "nodes": len(nodes), "materials": len(_items(doc, "materials")), "textures": len(_items(doc, "textures")),
        "images": images, "max_texture_px": max(sizes) if sizes and all(sizes) else None,
        "texture_memory_bytes_estimate": memory if images and memory_known else (0 if not images else None),
        "animations": animations, "skins": len(_items(doc, "skins")), "skinned_mesh_nodes": skinned,
        "extensions_used": _items(doc, "extensionsUsed"), "extensions_required": _items(doc, "extensionsRequired"),
        "bounds_m": bounds, "primitives_without_bounds": unbounded,
    }


BUDGET_KEYS = {
    "triangles": lambda s: s["triangles_in_scene"],
    "draw_calls": lambda s: s["draw_calls_in_scene"],
    "materials": lambda s: s["materials"],
    "textures": lambda s: s["textures"],
    "max_texture_px": lambda s: s["max_texture_px"] if s["images"] else 0,
    "texture_memory_mb": lambda s: None if s["texture_memory_bytes_estimate"] is None else s["texture_memory_bytes_estimate"] / 1048576,
    "file_size_mb": lambda s: s["file_size_bytes"] / 1048576,
}


def load_budgets(path):
    """Read a budgets file. Returns (profiles dict, error text or None)."""
    try:
        data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {}, f"budgets file {path} cannot be read: {exc}"
    profiles = data.get("profiles") if isinstance(data, dict) else None
    if not isinstance(profiles, dict) or not profiles:
        return {}, f"budgets file {path} has no profiles"
    return profiles, None


def check_budget(summary, profile):
    """Return one row per budget line: key, measured, limit, unit, state (ok, over, unknown), verified, source, checked."""
    rows = []
    for key, entry in profile.items():
        if not isinstance(entry, dict) or "value" not in entry:
            continue
        measure = BUDGET_KEYS.get(key)
        measured = measure(summary) if measure else None
        state = "unknown" if measured is None else ("ok" if measured <= entry["value"] else "over")
        rows.append({"key": key, "measured": None if measured is None else round(measured, 3), "limit": entry["value"],
                     "unit": entry.get("unit", ""), "state": state, "verified": bool(entry.get("verified")),
                     "source": entry.get("source", ""), "checked": entry.get("checked", "")})
    return rows


def describe(summary):
    """Lines of plain text for a stats summary."""
    lines = [
        f"file            {summary['file']} ({summary['kind']}, {summary['file_size_bytes']} bytes)",
        f"triangles       {summary['triangles_in_scene']} drawn in the default scene ({summary['meshes_unique_triangles']} stored)",
        f"draw calls      {summary['draw_calls_in_scene']} (one per primitive per use; an estimate, the engine may batch)",
        f"meshes          {summary['meshes']}, nodes {summary['nodes']}, materials {summary['materials']}, textures {summary['textures']}",
    ]
    for image in summary["images"]:
        size = f"{image['width']}x{image['height']}" if image["width"] else "size not readable"
        lines.append(f"image {image['index']:<9} {image['format']} {size}, {image['bytes']} bytes")
    estimate = summary["texture_memory_bytes_estimate"]
    lines.append("texture memory  " + ("not estimated (a compressed or unreadable image)" if estimate is None else
                                       f"{estimate / 1048576:.2f} MB estimate (RGBA8 with mip chain; compressed formats use less)"))
    for anim in summary["animations"]:
        lines.append(f"animation       '{anim['name']}' {anim['channels']} channels, {anim['duration_s']} s")
    if not summary["animations"]:
        lines.append("animations      none")
    bounds = summary["bounds_m"]
    if bounds:
        lines.append("bounding box    {:.4f} x {:.4f} x {:.4f} m (x, y, z); min {} max {}".format(*bounds["size"], bounds["min"], bounds["max"]))
        lines.append("                +Y is up in glTF; 1 unit is 1 metre")
    else:
        lines.append("bounding box    not available: no mesh in the scene carries POSITION min and max")
    if summary["skinned_mesh_nodes"]:
        lines.append("                the box is the bind pose of skinned meshes; an animation can move outside it")
    if summary["extensions_required"]:
        lines.append(f"needs extension {', '.join(summary['extensions_required'])}")
    return lines


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("file", help="a .glb or .gltf file")
    parser.add_argument("--json", action="store_true", help="print one JSON object instead of text")
    args = parser.parse_args()
    model = load(args.file)
    structure(model)
    summary = stats(model) if model.readable else None
    if args.json:
        print(json.dumps({"kind": model.kind, "errors": model.errors, "warnings": model.warnings, "stats": summary}, indent=2))
    else:
        for line in describe(summary) if summary else []:
            print(line)
        for warning in model.warnings:
            print(f"warning         {warning}")
        for error in model.errors:
            print(f"ERROR           {error}")
    if not model.readable:
        print(f"RESULT not verified: {model.errors[0] if model.errors else 'file could not be read'}")
        return 2
    if model.errors:
        print(f"RESULT fail: {len(model.errors)} structural errors")
        return 1
    print("RESULT pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
