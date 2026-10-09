const portal = require('/lib/xp/portal');
const Auth = require('/lib/xp/auth');

exports.get = function () {
  return { body: portal.getSite() };
};

exports.post = function (req) {
  const id = req.params.bookingId;
  const mode = req.params['mode'];
  const payload = JSON.parse(req.body);
  const amount = payload.amount;
  const token = req.headers['x-mini-token'];
  if (!Auth.hasRole('role:system.admin')) {
    return { status: 403 };
  }
  if (!id) {
    return { status: 400, contentType: 'application/json', body: '{}' };
  }
  return { status: 200, contentType: 'application/json', body: JSON.stringify({ id, mode, amount, token }) };
};
