# Arquitectura

## Problema

El usuario recibe proyectos desconocidos (C++ con CMake/Conan, APIs Spring Boot,
WAR en Tomcat, Android/Kotlin; más adelante Python y C#) y necesita:

1. entender estructura, build, dependencias, entry points, configuración, versiones;
2. levantarlo en su máquina;
3. después preguntar y editar código con un LLM **local**.

Hoy lo hace Claude Code. La meta es hacerlo con reglas + modelos locales.

## Por qué así (resumen; detalle en DECISIONS.md)

- El cuello de botella no es indexar sino **razonar con poco contexto**. Un
  modelo local de 27–35B rinde bien si recibe un resumen compacto y verificado
  en vez de explorar el repo a ciegas.
- Lo determinista (detectar stack, versiones, comandos de CI) lo hace un script:
  0 tokens, reproducible, con evidencia.
- La navegación de código bajo demanda la da LSP vía **Serena** (MCP), no un
  grafo precalculado ni embeddings.
- El usuario ejecuta los comandos (no Docker): control total y aprendizaje.

## Fases

### 1. recon (sin LLM)
Entrada: ruta del proyecto. Lee, nunca ejecuta.
- `ProjectScanner` lista archivos fuente (git ls-files o walk) y excluye
  carpetas generadas por marcadores (CMakeCache.txt, *.class, target/ junto a
  pom.xml…). Anota builds previos útiles.
- Ejecuta adaptadores registrados: `hints` (siempre) + adaptadores de stack cuyo
  `detect()` devuelva algo.
- Salida: `.project-ai/project.json` (+ `repo-map.md` cuando exista repomap).

### 2. doctor (sin LLM)
Ejecuta **solo comandos de versión** en la máquina del usuario (`java -version`,
`mvn -v`, `cmake --version`, `$CATALINA_HOME/bin/version.sh`, puertos de
servicios) y compara con `project.json`. Salida: `env-report.md` con ✅/❌/⚠ y
el comando exacto para corregir cada problema según el SO (macOS/Ubuntu).

### 3. runbook (sin LLM; LLM local opcional para redactar)
Combina `project.json` + `env-report.md` + `hints.commands` en pasos
ordenados (deps → configure → generate → build → test → run). Cada paso:
comando de shell con `tee` al log, alternativa en el IDE, criterio de éxito,
qué hacer si falla. Salida: `RUNBOOK.md`.

### 4. Ejecución humana
`<comando> 2>&1 | tee .project-ai/logs/step-03.log`

### 5. triage (escalado local)
```
N0  reglas (rules/*.toml + ~/.project-ai/rules.toml)   instantáneo
N1  modelo rápido  (nodo RTX 5070)                      la mayoría
N2  modelo pensador (nodo M1 Max)                       casos difíciles
N2b segunda opinión de otra familia (M1 Max)
N3  humano + documentación oficial
```
Cada intento queda en `journal.md`. Si un nivel resuelve, `triage --learn`
propone una regla nueva para N0 → el sistema mejora con el uso.
Paquete enviado al modelo: project.json resumido + env-report + error recortado
(primer error + ~40 líneas) + intentos previos. Nunca el repo entero.

### 6. finalize
Cuando build/run funcionan: marca comandos como `verified` y genera `AGENTS.md`
en la raíz del proyecto (100–200 líneas).

### 7. Trabajo diario
Agente (OpenCode recomendado; también Claude Code apuntando a Ollama) +
Serena (LSP: clangd, jdtls, kotlin-lsp, pyright, csharp-ls) + `AGENTS.md`.
El agente propone comandos; el usuario aprueba.

## Archivos de salida (`<proyecto>/.project-ai/`)

| Archivo | Lo genera | Contenido | Consumidor |
|---|---|---|---|
| `project.json` | recon | ProjectInfo serializado: stacks, requirements (con evidencia, prioridad, alternativas), modules, entry_points, endpoints, services, commands, facts, warnings | todas las fases, LLM |
| `repo-map.md` | recon (repomap) | módulos → archivos → símbolos (clases, firmas) sin cuerpos, ~2–4k tokens | LLM |
| `env-report.md` | doctor | requisito / tienes / estado / comando para arreglar | usuario, triage |
| `RUNBOOK.md` | runbook | pasos numerados con shell + IDE + "éxito si" + "si falla" | usuario |
| `logs/step-NN.log` | usuario (tee) | salida de cada paso | triage |
| `journal.md` | triage/finalize | historial: intento, nivel que resolvió, arreglo | todas, AGENTS.md |
| `escalation.md` | triage | paquete compacto para el nivel siguiente | modelo/humano |
| `AGENTS.md` (raíz) | finalize | resumen para agentes (ver plantilla abajo) | agente diario |

Global: `~/.project-ai/config.toml` (nodos/modelos), `~/.project-ai/rules.toml`
(reglas aprendidas, compartidas entre proyectos).

### Ejemplo de `env-report.md`
```
✅ Maven 3.9.6 (requiere >= 3.6 — pom.xml:12)
❌ JDK 8 requerido (pom.xml:9, .tool-versions:1) — tienes 21
   macOS:  sdk install java 8.0.392-tem && sdk use java 8.0.392-tem
⚠  Tomcat local 10.1 pero el código usa javax.* → necesitas Tomcat 9
⚠  PostgreSQL 13 requerido — nada escuchando en localhost:5432
```

### Ejemplo de paso en `RUNBOOK.md`
```
## Paso 3 — Compilar el WAR
Shell:    mvn -pl server -am -DskipTests package 2>&1 | tee .project-ai/logs/step-03.log
IntelliJ: Maven → server → Lifecycle → package (Skip Tests)
Éxito si: existe server/target/launcher.war
Si falla: project-ai triage step-03
Fuente:   README.md:517, pom.xml (módulos)
```

### Plantilla de `AGENTS.md`
1. Qué es (2 líneas) y stack.
2. Comandos **verificados** (build/test/run) — marcados con fecha.
3. Entorno: JDK, Tomcat, servicios, variables de entorno, perfiles.
4. Mapa: módulos y dónde vive cada cosa (controllers/resources, servicios, repos).
5. Trampas conocidas (del journal): p.ej. "javax → Tomcat 9", "-DskipITs".
6. Para más detalle: `.project-ai/repo-map.md`, `.project-ai/project.json`.

## Modelo de datos (project_ai/model.py)

- `Fact(value, priority, status, evidence[], adapter, note, alternatives[])`
- `SourcePriority`: EXPLICIT(4) > CI(3) > BUILD(2) > HEURISTIC(1) > DEFAULT(0)
  - EXPLICIT: .tool-versions, mise.toml, .sdkmanrc, wrappers, toolchain{} Gradle
  - CI: workflows, Jenkinsfile, Dockerfile, compose
  - BUILD: pom.xml, build.gradle, CMakeLists.txt, conanfile
  - HEURISTIC: deducciones y documentación
- `Status`: inferred | verified | default | missing | conflict
- Fusión (`add_requirement`): mayor prioridad gana; igual valor acumula
  evidencia; igual prioridad y distinto valor → gana el archivo menos profundo;
  misma profundidad → `conflict` + warning.
- `ProjectInfo`: root, stacks, requirements{}, modules[], entry_points[],
  endpoints[], services[], commands{}, facts{}, warnings[].

## Estructura del paquete

```
project_ai/
  model.py, scanner.py
  adapters/ __init__.py (orden de registro), base.py, hints.py, maven.py
            [cmake.py, conan.py, gradle.py, make.py, python.py, dotnet.py]
  [recon.py, repomap.py, doctor.py, runbook.py, triage.py, finalize.py,
   llm.py (cliente Ollama, stdlib urllib), config.py, cli.py]
rules/ *.toml  (reglas N0 incluidas en el paquete)
tests/ conftest.py (fixtures realistas), test_*.py
```
