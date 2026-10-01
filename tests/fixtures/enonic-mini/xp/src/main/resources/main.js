const eventLib = require('/lib/xp/event');

eventLib.listener({
  type: 'node.pushed',
  localOnly: false,
  callback: function () {},
});
