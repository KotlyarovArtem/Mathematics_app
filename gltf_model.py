# -*- coding: utf-8 -*-
"""
Загрузка и GPU-рендер 3D-моделей персонажей в формате GLB (glTF 2.0).

Модуль самодостаточен: разбор бинарного glTF (struct+json), извлечение
атрибутов (numpy), декодия JPEG-текстур через QImage и отрисовка
упрощённым PBR-шейдером (Cook-Torrance GGX) c normal-маппингом без
тангенсов (TBN через производные экрана). Внешние зависимости: moderngl,
numpy, PySide6.

Модели персонажей:
    fairy -> Images/Fairy/fairy_one.glb
    prime -> Images/Prime/War_Prime.glb

Пути ищутся: рядом с .exe (PyInstaller), в _MEIPASS и в папке скрипта.
"""
from __future__ import annotations

import json
import math
import os
import struct
from typing import List, Optional, Tuple

import numpy as np

# ---------------------------------------------------------------------------
#  Поиск файлов моделей
# ---------------------------------------------------------------------------
MODEL_FILES = {
    "fairy": os.path.join("Images", "Fairy", "fairy_one.glb"),
    "prime": os.path.join("Images", "Prime", "War_Prime.glb"),
}


def model_path(key: str) -> Optional[str]:
    """Возвращает путь к GLB-модели персонажа или None.

    Ищем в папке приложения (для PyInstaller --onedir это папка .exe),
    затем во временной папке распаковки (_MEIPASS, для --onefile).
    """
    rel = MODEL_FILES.get(key)
    if rel is None:
        return None
    import sys
    candidates = []
    if getattr(sys, "frozen", False):
        candidates.append(os.path.dirname(os.path.abspath(sys.executable)))
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(meipass)
    candidates.append(os.path.dirname(os.path.abspath(__file__)))
    for base in candidates:
        p = os.path.join(base, rel)
        if os.path.isfile(p):
            return p
    return None


# ---------------------------------------------------------------------------
#  Матричная математика (numpy, столбцовые матрицы как в OpenGL)
# ---------------------------------------------------------------------------
def mat_identity() -> np.ndarray:
    return np.eye(4, dtype=np.float32)


def mat_perspective(fov_y: float, aspect: float, near: float, far: float) -> np.ndarray:
    f = 1.0 / math.tan(fov_y / 2.0)
    m = np.zeros((4, 4), dtype=np.float32)
    m[0, 0] = f / aspect
    m[1, 1] = f
    m[2, 2] = (far + near) / (near - far)
    m[2, 3] = 2.0 * far * near / (near - far)
    m[3, 2] = -1.0
    return m


def mat_look_at(eye, center, up) -> np.ndarray:
    eye = np.asarray(eye, dtype=np.float32)
    center = np.asarray(center, dtype=np.float32)
    up = np.asarray(up, dtype=np.float32)
    f = center - eye
    f = f / np.linalg.norm(f)
    s = np.cross(f, up)
    s = s / np.linalg.norm(s)
    u = np.cross(s, f)
    m = np.eye(4, dtype=np.float32)
    m[0, :3], m[1, :3], m[2, :3] = s, u, -f
    m[0, 3] = -s @ eye
    m[1, 3] = -u @ eye
    m[2, 3] = f @ eye
    return m


def mat_translate(x: float, y: float, z: float) -> np.ndarray:
    m = np.eye(4, dtype=np.float32)
    m[:3, 3] = (x, y, z)
    return m


def mat_scale(s: float) -> np.ndarray:
    m = np.eye(4, dtype=np.float32)
    m[0, 0] = m[1, 1] = m[2, 2] = s
    return m


def mat_rotate_y(a: float) -> np.ndarray:
    c, s = math.cos(a), math.sin(a)
    m = np.eye(4, dtype=np.float32)
    m[0, 0], m[0, 2] = c, s
    m[2, 0], m[2, 2] = -s, c
    return m


def mat_rotate_x(a: float) -> np.ndarray:
    c, s = math.cos(a), math.sin(a)
    m = np.eye(4, dtype=np.float32)
    m[1, 1], m[1, 2] = c, -s
    m[2, 1], m[2, 2] = s, c
    return m


def mat_mul(*ms) -> np.ndarray:
    out = ms[0]
    for m in ms[1:]:
        out = (out @ m).astype(np.float32)
    return out


# ---------------------------------------------------------------------------
#  Разбор GLB
# ---------------------------------------------------------------------------
_COMPONENTS = {5120: ("b", 1), 5121: ("B", 1), 5122: ("h", 2),
               5123: ("H", 2), 5125: ("I", 4), 5126: ("f", 4)}
_TYPE_COUNT = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def _parse_glb(path: str) -> Tuple[dict, bytes]:
    """Возвращает (gltf-json, bin-chunk)."""
    data = open(path, "rb").read()
    magic, version, length = struct.unpack_from("<III", data, 0)
    if magic != 0x46546C67:
        raise ValueError(f"Не GLB-файл: {path}")
    offset = 12
    gltf = None
    blob = b""
    while offset + 8 <= min(length, len(data)):
        chunk_len, chunk_type = struct.unpack_from("<II", data, offset)
        chunk = data[offset + 8:offset + 8 + chunk_len]
        if chunk_type == 0x4E4F534A:          # JSON
            gltf = json.loads(chunk)
        elif chunk_type == 0x004E4942:        # BIN
            blob = chunk
        offset += 8 + chunk_len
    if gltf is None:
        raise ValueError(f"Нет JSON-чанка: {path}")
    return gltf, blob


def _read_accessor(gltf: dict, blob: bytes, accessor_idx: int) -> np.ndarray:
    """Читает accessor в numpy-массив формы (count, n)."""
    acc = gltf["accessors"][accessor_idx]
    bvi = acc.get("bufferView", 0)
    bv = gltf["bufferViews"][bvi]
    comp_char, comp_size = _COMPONENTS[acc["componentType"]]
    n = _TYPE_COUNT[acc["type"]]
    stride = bv.get("byteStride") or (comp_size * n)
    count = acc["count"]
    start = bv.get("byteOffset", 0) + acc.get("byteOffset", 0)
    # Быстрый путь: плотно упакованные float-атрибуты.
    if stride == comp_size * n:
        fmt = np.dtype(np.uint8) if comp_char in "BH" else (
            np.float32 if comp_char == "f" else
            (np.uint16 if comp_char == "H" else np.int16))
        if comp_char == "I":
            fmt = np.dtype(np.uint32)
        if comp_char == "B":
            fmt = np.dtype(np.uint8)
        if comp_char == "b":
            fmt = np.dtype(np.int8)
        arr = np.frombuffer(blob, dtype=fmt, count=count * n, offset=start)
        return arr.reshape(count, n).copy()
    # Медленный путь: есть byteStride.
    out = np.zeros((count, n), dtype=np.float32)
    for i in range(count):
        off = start + i * stride
        vals = struct.unpack_from(f"<{n}{comp_char}", blob, off)
        out[i] = vals
    return out


def _decode_image(blob: bytes, bv: dict) -> "QImage":
    """Декодирует встроенное изображение (JPEG/PNG) через QImage."""
    from PySide6.QtGui import QImage
    start = bv.get("byteOffset", 0)
    length = bv["byteLength"]
    raw = bytes(blob[start:start + length])
    img = QImage()
    ok = img.loadFromData(raw)
    if not ok or img.isNull():
        raise ValueError("Не удалось декодировать текстуру модели")
    return img.convertToFormat(QImage.Format.Format_RGBA8888)


# ---------------------------------------------------------------------------
#  Шейдеры модели: PBR (Cook-Torrance GGX) + tangentless normal mapping
# ---------------------------------------------------------------------------
MODEL_VS = """
#version 330
in vec3 in_pos;
in vec3 in_norm;
in vec2 in_uv;
uniform mat4 u_mvp;
uniform mat4 u_model;
out vec3 v_norm;
out vec2 v_uv;
out vec3 v_world;
void main() {
    vec4 world = u_model * vec4(in_pos, 1.0);
    v_world = world.xyz;
    v_norm = normalize(mat3(u_model) * in_norm);
    v_uv = in_uv;
    gl_Position = u_mvp * vec4(in_pos, 1.0);
}
"""

MODEL_FS = """
#version 330
in vec3 v_norm;
in vec2 v_uv;
in vec3 v_world;
out vec4 f_color;
uniform sampler2D u_base;      // sRGB baseColor
uniform sampler2D u_mr;        // G=roughness, B=metallic
uniform sampler2D u_nrm;       // normal map (OpenGL-конвенция)
uniform vec3 u_eye;

const vec3 L_KEY  = normalize(vec3(0.45, 0.85, 0.55));   // тёплый ключевой
const vec3 L_FILL = normalize(vec3(-0.7, 0.25, 0.4));   // холодный заполняющий
const vec3 L_RIM  = normalize(vec3(0.0, 0.4, -1.0));    // контровой

vec3 srgb_to_linear(vec3 c) { return pow(c, vec3(2.2)); }
vec3 linear_to_srgb(vec3 c) { return pow(max(c, 0.0), vec3(1.0 / 2.2)); }

vec3 apply_normal_map(vec3 n, vec3 view_dir) {
    // TBN без тангенсов: через производные экрана.
    vec3 dp1 = dFdx(v_world);
    vec3 dp2 = dFdy(v_world);
    vec2 du1 = dFdx(v_uv);
    vec2 du2 = dFdy(v_uv);
    vec3 dp2perp = cross(dp2, n);
    vec3 dp1perp = cross(n, dp1);
    vec3 t = dp2perp * du1.x + dp1perp * du2.x;
    vec3 b = dp2perp * du1.y + dp1perp * du2.y;
    float len = max(dot(t, t), dot(b, b));
    if (len < 1e-8) return n;
    float invmax = inversesqrt(len);
    mat3 tbn = mat3(t * invmax, b * invmax, n);
    vec3 tn = texture(u_nrm, v_uv).xyz * 2.0 - 1.0;
    return normalize(tbn * tn);
}

float ggx(vec3 n, vec3 v, vec3 l, float rough) {
    float a = max(rough * rough, 0.002);
    vec3 h = normalize(v + l);
    float ndh = max(dot(n, h), 0.0);
    float ndv = max(dot(n, v), 0.001);
    float ndl = max(dot(n, l), 0.0);
    float d = ndh * ndh * (a * a - 1.0) + 1.0;
    d = a * a / (3.14159265 * d * d);
    float k = a * 0.5;
    float gv = ndv / (ndv * (1.0 - k) + k);
    float gl = ndl / (ndl * (1.0 - k) + k);
    return d * gv * gl / (4.0 * ndv * ndl + 0.001) * ndl;
}

void main() {
    vec3 albedo = srgb_to_linear(texture(u_base, v_uv).rgb);
    vec2 mr = texture(u_mr, v_uv).gb;
    float rough = clamp(mr.x, 0.05, 1.0);
    float metal = clamp(mr.y, 0.0, 1.0);
    vec3 v = normalize(u_eye - v_world);
    vec3 n0 = normalize(v_norm);
    if (!gl_FrontFacing) n0 = -n0;
    vec3 n = apply_normal_map(n0, v);

    // Освещение: ключевой + заполняющий + контровой (объём).
    vec3 base = mix(albedo, vec3(0.04), metal);
    vec3 spec_tint = mix(vec3(1.0), albedo, metal);
    vec3 col = albedo * 0.25 * (0.6 + 0.4 * n.y);      // hemisphere ambient
    col += base * max(dot(n, L_KEY), 0.0) * vec3(1.0, 0.96, 0.88) * 1.15;
    col += base * max(dot(n, L_FILL), 0.0) * vec3(0.55, 0.65, 0.9) * 0.45;
    col += spec_tint * ggx(n, v, L_KEY, rough) * vec3(1.0, 0.95, 0.85) * 1.4;
    col += spec_tint * ggx(n, v, L_FILL, rough) * vec3(0.6, 0.7, 1.0) * 0.5;
    float rim = pow(1.0 - max(dot(n, v), 0.0), 3.0);
    col += rim * vec3(0.45, 0.65, 1.0) * 0.35;          // голубой контровой

    // Мягкая тонмапа и гамма.
    col = col / (col + vec3(0.85));
    col *= 1.25;
    f_color = vec4(linear_to_srgb(col), 1.0);
}
"""

# Мягкая тень-эллипс под персонажем.
SHADOW_VS = """
#version 330
in vec2 in_pos;
uniform mat4 u_mvp;
uniform vec3 u_center;
uniform vec2 u_radii;
out vec2 v_q;
void main() {
    v_q = in_pos;
    vec3 world = u_center + vec3(in_pos.x * u_radii.x, 0.0,
                                 in_pos.y * u_radii.y);
    gl_Position = u_mvp * vec4(world, 1.0);
}
"""

SHADOW_FS = """
#version 330
in vec2 v_q;
out vec4 f_color;
uniform float u_strength;
void main() {
    float r = length(v_q);
    float a = (1.0 - smoothstep(0.0, 1.0, r)) * u_strength;
    f_color = vec4(0.03, 0.04, 0.08, a);
}
"""


# ---------------------------------------------------------------------------
#  Модель на GPU
# ---------------------------------------------------------------------------
class GLTFModel:
    """Загруженная GLB-модель: геометрия, текстуры, габариты, ресурсы GL."""

    def __init__(self, ctx, path: str):
        import moderngl
        self._ctx = ctx
        self._moderngl = moderngl
        gltf, blob = _parse_glb(path)
        self._gltf = gltf

        prim = gltf["meshes"][0]["primitives"][0]
        attrs = prim["attributes"]
        if "POSITION" not in attrs or "NORMAL" not in attrs:
            raise ValueError("Модель без POSITION/NORMAL не поддерживается")

        positions = _read_accessor(gltf, blob, attrs["POSITION"]).astype(np.float32)
        normals = _read_accessor(gltf, blob, attrs["NORMAL"]).astype(np.float32)
        uvs = (_read_accessor(gltf, blob, attrs["TEXCOORD_0"]).astype(np.float32)
               if "TEXCOORD_0" in attrs else
               np.zeros((len(positions), 2), dtype=np.float32))
        indices = (_read_accessor(gltf, blob, prim["indices"]).astype(np.uint32)
                   if prim.get("indices") is not None else
                   np.arange(len(positions), dtype=np.uint32))
        self.vertex_count = len(positions)
        self.index_count = len(indices)

        # Интерливинг pos+norm+uv одним буфером (быстрая загрузка на GPU).
        inter = np.concatenate([positions, normals, uvs], axis=1).astype(np.float32)
        self._vbo = ctx.buffer(inter.tobytes())
        self._ibo = ctx.buffer(indices.astype("u4").tobytes())
        self._prog = ctx.program(vertex_shader=MODEL_VS, fragment_shader=MODEL_FS)
        self._vao = ctx.vertex_array(
            self._prog,
            [(self._vbo, "3f 3f 2f", "in_pos", "in_norm", "in_uv")],
            index_buffer=self._ibo, index_element_size=4)

        # Текстуры материала.
        mat = gltf["materials"][prim.get("material", 0)]
        pbr = mat.get("pbrMetallicRoughness", {})
        self._tex_base = self._load_texture(gltf, blob, pbr.get("baseColorTexture"))
        mr_tex = pbr.get("metallicRoughnessTexture")
        nrm_tex = mat.get("normalTexture")
        self._tex_mr = self._load_texture(gltf, blob, mr_tex, default=(1.0, 0.0, 0.6))
        self._tex_nrm = self._load_texture(gltf, blob, nrm_tex, default=(0.5, 0.5, 1.0))

        # Габариты (для камеры и тени).
        acc = gltf["accessors"][attrs["POSITION"]]
        self.bmin = np.array(acc.get("min", (0, 0, 0)), dtype=np.float32)
        self.bmax = np.array(acc.get("max", (1, 1, 1)), dtype=np.float32)

        # Тень.
        self._shadow_prog = ctx.program(vertex_shader=SHADOW_VS,
                                        fragment_shader=SHADOW_FS)
        quad = np.array([-1, -1, 1, -1, 1, 1, -1, 1], dtype=np.float32)
        self._shadow_vbo = ctx.buffer(quad.tobytes())
        self._shadow_vao = ctx.vertex_array(
            self._shadow_prog, [(self._shadow_vbo, "2f", "in_pos")])

    # ------------------------------------------------------------------
    def _load_texture(self, gltf, blob, tex_ref, default=None):
        """Грузит текстуру материала (или плоский цвет по умолчанию)."""
        import moderngl
        if tex_ref is None and default is not None:
            img = QImage_solid(default)
        else:
            tex = gltf["textures"][tex_ref["index"]]
            img = _decode_image(blob, gltf["bufferViews"][gltf["images"][tex["source"]]["bufferView"]])
        tex = self._ctx.texture((img.width(), img.height()), 4, img.bits(), alignment=1)
        tex.filter = (moderngl.LINEAR_MIPMAP_LINEAR, moderngl.LINEAR)
        tex.build_mipmaps()
        tex.repeat_x = tex.repeat_y = True
        return tex

    # ------------------------------------------------------------------
    def draw(self, proj_view: np.ndarray, model: np.ndarray, eye) -> None:
        """Рисует модель и мягкую тень под ней."""
        mvp = (proj_view @ model).astype(np.float32)
        center_world = (model @ np.array([*(self.bmin + self.bmax) / 2.0, 1.0],
                                         dtype=np.float32)).astype(np.float32)
        # GLSL ждёт матрицы в column-major: загружаем транспонированный
        # flatten (наша математика -- row-major, result = M @ v).
        mvp_t = tuple(mvp.T.reshape(-1))
        # Тень (до модели, без записи в depth).
        self._shadow_prog["u_mvp"].value = mvp_t
        self._shadow_prog["u_center"].value = tuple(center_world[:3])
        radii = float((self.bmax[0] - self.bmin[0]) * 0.62), \
            float((self.bmax[2] - self.bmin[2]) * 0.75)
        self._shadow_prog["u_radii"].value = radii
        self._shadow_prog["u_strength"].value = 0.42
        self._ctx.disable(self._moderngl.DEPTH_TEST)
        self._shadow_vao.render(self._moderngl.TRIANGLE_FAN)
        self._ctx.enable(self._moderngl.DEPTH_TEST)

        # Модель.
        self._tex_base.use(0)
        self._tex_mr.use(1)
        self._tex_nrm.use(2)
        self._prog["u_base"].value = 0
        self._prog["u_mr"].value = 1
        self._prog["u_nrm"].value = 2
        self._prog["u_mvp"].value = mvp_t
        self._prog["u_model"].value = tuple(np.asarray(model).T.reshape(-1))
        self._prog["u_eye"].value = tuple(np.asarray(eye, dtype=np.float32))
        self._vao.render(self._moderngl.TRIANGLES)

    # ------------------------------------------------------------------
    def release(self) -> None:
        """Освобождает все GL-ресурсы модели."""
        for res in (self._vao, self._shadow_vao):
            try:
                if res is not None:
                    res.release()
            except Exception:
                pass
        for res in (self._prog, self._shadow_prog, self._vbo, self._ibo,
                    self._shadow_vbo, self._tex_base, self._tex_mr,
                    self._tex_nrm):
            try:
                if res is not None:
                    res.release()
            except Exception:
                pass
        self._vao = self._shadow_vao = None
        self._prog = self._shadow_prog = None
        self._vbo = self._ibo = self._shadow_vbo = None
        self._tex_base = self._tex_mr = self._tex_nrm = None


def QImage_solid(color) -> "QImage":
    """Однотонная текстура-заглушка 4x4."""
    from PySide6.QtGui import QImage, QColor
    r, g, b = [int(c * 255) for c in color[:3]]
    img = QImage(4, 4, QImage.Format.Format_RGBA8888)
    img.fill(QColor(r, g, b, 255))
    return img


# ---------------------------------------------------------------------------
#  Камера под габариты модели
# ---------------------------------------------------------------------------
def fit_camera(bmin, bmax, aspect: float, fov=math.radians(32.0)):
    """Возвращает (proj, view, eye) для вписывания модели в кадр."""
    center = (bmin + bmax) / 2.0
    radius = float(np.linalg.norm(bmax - bmin) / 2.0)
    dist = radius / math.tan(fov / 2.0) * 1.12
    eye = np.array([0.0, center[1] + radius * 0.28, dist], dtype=np.float32)
    proj = mat_perspective(fov, max(aspect, 0.1), dist * 0.05, dist * 4.0)
    view = mat_look_at(eye, np.array([0.0, center[1], 0.0], dtype=np.float32),
                       np.array([0.0, 1.0, 0.0], dtype=np.float32))
    return proj, view, eye
