# demo/

Walkthrough end-to-end del ciclo completo Fase 1 + Fase 2.

## Ejecutar

```powershell
.venv\Scripts\python.exe -m demo.v0_walkthrough
```

Sin red, sin persistencia en el repo. Escribe a `tempfile.TemporaryDirectory` que se borra al salir.

## Qué muestra

Ver [`docs/walkthrough.md`](../docs/walkthrough.md) para descripción y output esperado.

## Qué NO es

- **No es código de producción.** No se cubre con tests. No importable desde `src/`.
- **No es benchmark.** Para benchmarks ver [`benchmarks/`](../benchmarks/).
- **No es CI.** No corre automáticamente.

Es la carta de presentación operacional del proyecto post-Fase 2.
