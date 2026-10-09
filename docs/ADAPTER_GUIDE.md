# Guía para escribir un adaptador

## Checklist

1. Leer `adapters/base.py` (contrato y helpers) y un adaptador existente
   (`maven.py` es el más completo; `hints.py` el transversal).
2. Crear fixture realista en `tests/conftest.py` (diccionario ruta→contenido)
   imitando un proyecto real del stack. Incluir trampas: archivos generados,
   docs con comandos, configuraciones antiguas.
3. Escribir `tests/test_<stack>.py` con lo que debe salir (requirements,
   modules, entry_points, endpoints, services, commands, facts, warnings).
4. Implementar `adapters/<stack>.py` con `@register` e importarlo en
   `adapters/__init__.py` **después de `hints`**.
5. `uv run pytest -q` y `pyflakes` limpios.
6. Probar con un proyecto real del usuario (`/probar-real <ruta>`); cada
   discrepancia → nuevo caso en el fixture.
7. Actualizar CLAUDE.md (estado), ROADMAP (✅) y DECISIONS si aplica.

## Contrato

```python
@register
class XAdapter(Adapter):
    name = "x"                    # único
    always_run = False            # True solo para señales transversales

    def detect(self, sc) -> list[StackDetection]:
        # barato: nombres de archivo, leer poco. Puede devolver varias raíces.
    def analyze(self, sc, info, detections) -> None:
        # lee a fondo y vuelca en info; NUNCA ejecuta ni escribe
```
`run_adapters` captura excepciones por adaptador (aviso, no caída). Guardar
estado parseado en `self` es válido: hay una instancia por ejecución.

## Prioridades (SourcePriority)

| Fuente | Prioridad |
|---|---|
| .tool-versions, mise.toml, .sdkmanrc, wrapper de Maven/Gradle, toolchain{} | EXPLICIT |
| CI, Dockerfile, docker-compose | CI |
| archivo de build (pom, build.gradle, CMakeLists, conanfile, csproj, pyproject) | BUILD |
| deducciones (Spring Boot 3 ⇒ JDK 17), docs, IDE local | HEURISTIC |

## Claves de requisitos estándar (`base.REQUIREMENT_KEYS`)
`jdk`, `jdk_runtime`, `maven`, `gradle`, `kotlin`, `android_agp`,
`android_compile_sdk`, `tomcat`, `cmake`, `conan`, `ninja`, `gcc`, `clang`,
`cxx_standard`, `python`, `node`, `dotnet`, `go`.
Añadir una clave nueva = añadirla a la tabla y a `docs/COMMANDS.md` §4
(cómo la comprobará doctor).

## Helpers (base.py)
- `req(info, key, raw, priority, file, line, snippet, adapter=, note=)` —
  normaliza la versión (`temurin-17.0.2` → `17`) y fusiona.
- `add_cmd_hint(...)` — comando visto fuera del build (CI/docs/IDE); se
  deduplica y clasifica (deps/configure/test/build/run/script/ops).
- `add_service(info, kind, version, priority, file, line, snippet, adapter=)`.
- `info.set_fact(key, Fact)` — hecho escalar; gana mayor prioridad.
- `info.add_list_fact(key, item, priority=, evidence=)` — listas sin duplicados.
- `info.add_command(Command(name, shell, cwd, ide_hint, success_hint, fact))` —
  comandos propuestos por el adaptador. Nombres: `deps`, `configure`,
  `generate`, `build`, `build_app`, `test`, `run`.
- `ev(file, line, snippet)`, `first_match`, `all_matches`, `jdk_major`,
  `normalize_version`.

## Convenciones de facts
Prefijo por adaptador (`maven.*`, `cmake.*`, `conan.*`, `gradle.*`) y
prefijos compartidos: `hints.*`, `ide.*`, `db.*`, `runtime.*`, `framework`,
`java.ee_namespace`, `jdk_ceiling`, `config.*`.
Riesgos para el usuario → `info.warnings` (frases completas, con la acción
sugerida). Datos útiles → facts con `note` explicando qué hacer con ellos.

## Estilo
- Solo stdlib. Regex robustas y comentadas; XML con ElementTree (quitar
  namespaces); TOML con tomllib; JSON con json (JSONC: regex o quitar comentarios).
- Siempre con evidencia (archivo y, si se puede, línea).
- Mejor `HEURISTIC` + nota que un dato falso con prioridad alta.
- Límites para repos grandes: cortar lecturas masivas (p.ej. 4000 archivos) y
  avisar si se trunca.
