# Fixed-building workspace integration preview

2026-10-16: User accepted the preview and explicitly authorized the scoped main-workspace merge. Implementation and verification are recorded in [the integration review](../../reviews/2026-10-16-fixed-building-workspace-integration.md).

User request: add the previously reviewed rotatable, per-floor 3D building preview under a separate main-workbench entry, show its effect before merging. User confirmed the 3D preview and the name “固定建筑压力分析”.

Scope: geometry display and the already approved supplied-pressure workflow only. Do not change the existing refined-building-blast flow, add explosive configuration, generate FE meshes or launch native solving.

1. Add an independent main-app adapter and portable structural-only resource, preserving the checked six retained structural files. Read-only 3D metadata must refer to the same fixed template as pressure export.
2. Restore three-dimensional orbit, floor cutaway, plan/front views, room labels and layer controls. Link to pressure settings as a separate workspace tab. No mutable building-design settings.
3. Prepare the main navigation/server patch against the user's current files without applying or committing their unrelated modifications. Run an integration preview server on a separate port using the current main app and only the new adapter/assets.
4. Run scoped unit/HTTP and browser view/navigation checks. No full or heavy regression. Show the preview URL and actual screenshots for review.
5. Merge only after the user has viewed the requested preview. Preserve main-workspace changes, isolated worktree and historical evidence. Do not merge the entire dirty architecture branch or its unrelated modeling/explosive changes.

Review concerns: dependency on old explosion modules; metadata/template mismatch; packaged ZIP traversal or mutation; old-route/navigation regressions; 3D interior visibility and memory/resource disposal.
