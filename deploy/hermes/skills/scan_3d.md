# Hermes Skill: Live 3D Scanning & Target Modeling

## Goal
Execute "find item X and 3D model it" autonomous scanning tasks.

## Procedure
1. When asked to scan or 3D model an object:
   - Call `scan_target_object(target_label="<item_name>", radius_m=3.0)`.
2. This automatically:
   - Locates the object in the camera viewport.
   - Computes target centroid.
   - Mints a motion token and initiates an inspection `orbit` mode around the object.
   - Accumulates synchronized 3D point cloud slices.
3. Once the orbit finishes or user requests completion:
   - Call `stop_3d_scan()`.
   - Export path (`.ply` format), total point count, and spatial bounds are returned.
4. Inform operator of the model results and provide the session ID for timeline scrubbing in the Web UI.
