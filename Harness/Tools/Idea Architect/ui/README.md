# Task Drawer UI assets

This dependency-free UI package owns the reusable Task Companion drawer assets.

- Runtime assets live in ../src/idea_architect/static/ so the Python dashboard can serve them from the same origin.
- The drawer consumes only GET /api/v1/tasks; it never changes task state.
- Pure data selection and contract checks live in task-drawer-model.js.
- Run the JavaScript tests with pnpm install --frozen-lockfile && pnpm test.

No npm commands or runtime JavaScript dependencies are used.
