---
id: how-to-traverse-an-xp7-cms-through-guillotine-and-content-studio
when_skills: [extract-legacy, extract-agentic, run-plan, plan-task-evidence, develop-xp7-backend]
inputs: [live XP7 session, project name, site content key]
outputs: [page component trees, content lists, site config values]
stop_if: [the host is production, the session answers 401]
read: section
prose: caveman-lite
---

# How to traverse an XP7 CMS through Guillotine and Content Studio

Calibrated 2026-09 on XP 7.14 to 7.16 with Content Studio 5.2.x. Log in first: [How-to-log-in-to-an-xp7-admin-and-keep-the-session.md](How-to-log-in-to-an-xp7-admin-and-keep-the-session.md). Every call below needs the session cookie. Local or review XP only.

## Names to know

- Project: Content Studio's unit of content (repository `com.enonic.cms.<project>`). The calibrated installs used `en`; do not assume it. List the real names: `GET /admin/rest-v2/cs/project/list`.
- Branch: `draft` (editor state) or `master` (published). Evidence of what a visitor sees comes from `master`.
- Site key: the site content, for example `/en`. Page templates sit in `<site key>/_templates`.
- A content `_path` starts at the site (`/en/about`). A Content Studio query path starts at `/content/` (`/content/en/about`).

## Surfaces

| Surface | URL (prefix with the base) |
|---|---|
| Browse | `/admin/tool/com.enonic.app.contentstudio/main/<project>/browse` |
| Edit deep link | `/admin/tool/com.enonic.app.contentstudio/main/<project>/edit/<content-uuid>` |
| Guillotine widget | `/admin/tool/com.enonic.app.contentstudio/main#/<project>/widget/guillotine/guillotine` |
| Guillotine POST | `/admin/site/preview/<project>/<branch>` |
| Content Studio REST | `/admin/rest-v2/cs/...` |

The browse grid does not accept a content id as an expand instruction. `…/browse/<uuid>` still renders the collapsed root. Use REST or Guillotine to find a content item, then open its edit deep link.

## Procedure

1. Read a page and its component tree through Guillotine. POST JSON `{"query": "..."}` to the preview URL:

```graphql
query {
  guillotine {
    get(key: "/en") {
      _id
      _path
      type
      displayName
      pageAsJson
      components { path type }
    }
  }
}
```

`pageAsJson` holds the page `descriptor`, the parts and layouts with their `config`, and fragments. Do not query `components { descriptor }`: it is undefined on this schema.

2. List children one level at a time: `guillotine { getChildren(key: "/en", first: 100) { _id _path _name type displayName } }`. Recurse only as far as the task needs.
3. Sample a content type without walking the tree:

```graphql
query { guillotine { queryConnection(query: "", first: 3, contentTypes: ["<app>:<type>"]) {
  totalCount edges { node { _id _path displayName type pageAsJson } } } } }
```

4. Count usage of a descriptor exhaustively: `queryConnection(query: "components.part.descriptor = '<app>:<part>'", first: 0) { totalCount }`. `page` and `layout` work the same way. A query error means the schema lacks the field. Degrade, do not fail the survey.
5. Query one content type through Content Studio REST. `contentTypeNames` is mandatory and omitting it returns HTTP 500 with `"contentTypeNames" is null`. Pass `[]` for any type:

```js
await fetch('/admin/rest-v2/cs/cms/<project>/content/content/query', {
  method: 'POST', headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({queryExpr: "_path LIKE '/content/*' ORDER BY _path ASC",
    contentTypeNames: ['<app>:<type>'], from: 0, size: 100, expand: 'summary'})
}).then(r => r.json());
```

Each hit carries `displayName`, `path`, `id`, `type` and `publish`.

6. Read one item by id: `GET /admin/rest-v2/cs/cms/<project>/content/content?id=<uuid>`.
7. Read the Site Config. It is stored on the site content, in `data`: fetch the site by id and walk `data[0].values[0].set`. The entry named `config` holds the app's config, and a `Reference` value carries the target content uuid. The site config form is not on the site wizard page. In the UI it sits behind the cog on the app's row in the **Applications** selector.
8. Resolve which page template a page uses, in this order: the page's own customized page, then an explicit `page.template` reference, then the first template in `_templates` (folder order) whose `data.supports` matches the content type.
9. Choose what to survey: the site root, the `_templates` folder, one page per distinct page descriptor, and one content per content type. Add the content that holds the Site Config.

## With extractkit

`extractkit step enonic.cms` makes these calls. `--cms-key` pins the site and page keys for the page fetch and the Site Config harvest. `--round2 <context>` surveys that context's keys a second time. `--project` and `--branch` build the preview URL, or pass `--guillotine` yourself. The Config Env admin tool is read as HTML from `--configenv` or the profile's `configenv_path`. A 404 there only means the tool is not installed.

## Pitfalls

- `POST /_/service/com.enonic.app.guillotine/graphql` answers 404 on this stack. Use the preview URL.
- A project's own GraphQL service called from the admin origin can return empty `getChildren`. Call it from the public site host, or use the preview URL.
- A component can exist on `draft` and not on `master`. Check the branch and the publish state before treating a page as live.
- Do not assume the language segment of a content path is the public URL's language segment.
- The Guillotine Query Playground schema explorer can fail with `Enum values cannot be named: false` while POST queries still return data.
- A `401` or `403` means the session is stale. Re-mint it. Do not retry with the same cookie.
- Secrets live in Site Config and Config Env. Report keys and shapes, never the values of keys, tokens or passwords.
- Raw node queries, ACL checks and node edits are the Data Toolbox's job (`/admin/tool/systems.rcd.enonic.datatoolbox/data-toolbox`), not Guillotine's. Use it only as a fallback and record that you did.
