import * as portal from '/lib/xp/portal';
import { getChildren as children } from '/lib/xp/content';

export function get(req: Request) {
  const site = portal.getSite();
  return { body: children({ key: site._id }) };
}

export const post = () => ({ status: 405 });
