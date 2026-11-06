# Planificador de turnos

Prototipo basado en el documento de preparación del proyecto: genera un cuadrante de cuatro semanas para ocho personas y tres turnos. OR-Tools CP-SAT asigna el trabajo; un verificador separado vuelve a comprobar las reglas obligatorias.

## Reglas del prototipo

- Cobertura mínima configurable para mañana, tarde y noche (por defecto 2, 2 y 1 personas).
- Al menos 12 horas entre el final de un turno y el inicio del siguiente.
- Máximo de cinco turnos por semana, configurable por persona según su contrato.
- No más de cinco días trabajados consecutivos.
- Vacaciones y días aprobados como no disponibles.
- Turnos para los que cada persona está habilitada y turnos ya fijados.
- Peticiones de turnos fijos y preferencias de turnos; las preferencias no son obligatorias.
- Reparto equilibrado del total de turnos, noches y fines de semana cuando las reglas lo permiten.
- Verificación independiente y aprobación humana antes de publicar.

Los horarios usados son mañana 06:00–14:00, tarde 14:00–22:00 y noche 22:00–06:00. El prototipo no contiene un convenio ni certifica cumplimiento laboral: hay que confirmar los descansos, límites y reglas con la normativa y el convenio aplicables.

## Ejecutar en Windows

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```

Abre `http://127.0.0.1:8000`. Ajusta el lunes de inicio, la cobertura, los nombres, los máximos semanales, las ausencias y las preferencias; genera el cuadrante y revísalo antes de aprobarlo.

También se puede ejecutar con Docker:

```powershell
docker compose up --build
```

## API

- `GET /api/scenario`: valores iniciales del ejemplo.
- `POST /api/schedules`: valida el JSON, resuelve y verifica un cuadrante. Devuelve `409` si las restricciones son incompatibles.
- `POST /api/schedules/<id>/approve`: registra la aprobación humana tras volver a verificarlo.

El cuerpo de `POST /api/schedules` admite `start_date` (lunes en formato `AAAA-MM-DD`), `coverage`, `employees` y, opcionalmente, `fixed_assignments`. Cada persona puede incluir `max_shifts_per_week`, `unavailable_dates`, `eligible_shifts`, `preferred_shifts` y `preferred_assignments`. Los turnos fijos globales se envían en `fixed_assignments`. Los turnos se identifican como `morning`, `afternoon` y `night`.

Los cuadrantes y aprobaciones se guardan en memoria únicamente para esta demostración; se pierden al reiniciar el proceso. La extracción de lenguaje natural, RAG de convenios y la publicación persistente quedan fuera de este prototipo inicial.

## Pruebas

```powershell
python -m unittest discover -s tests -v
```
