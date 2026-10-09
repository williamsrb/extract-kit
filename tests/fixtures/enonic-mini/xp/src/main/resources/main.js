const eventLib = require('/lib/xp/event');
const Booking = require('/lib/mini-booking');

eventLib.listener({
  type: 'node.pushed',
  localOnly: false,
  callback: function () {},
});

eventLib.listener({
  type: 'custom.booking.paid',
  localOnly: false,
  callback: function (event) {
    Booking.sweep(event);
  },
});
