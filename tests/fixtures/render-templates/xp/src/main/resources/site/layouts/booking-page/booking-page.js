const thymeleaf = require('/lib/thymeleaf');

exports.get = function (req) {
  const booking = req.params.bookingId;
  const view = booking ? resolve('booking-page.html') : resolve('no-booking.html');
  return { body: thymeleaf.render(view, { booking }) };
};
