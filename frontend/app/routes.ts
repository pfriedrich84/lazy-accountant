import {
  type RouteConfig,
  index,
  layout,
  route,
} from "@react-router/dev/routes";
export default [
  layout("routes/shell.tsx", [
    index("routes/home.tsx"),
    route("documents", "routes/documents.tsx"),
    route("documents/:documentId", "routes/document.tsx"),
    route("months", "routes/months.tsx"),
    route("packages", "routes/packages.tsx"),
    route("settings", "routes/settings.tsx"),
  ]),
] satisfies RouteConfig;
