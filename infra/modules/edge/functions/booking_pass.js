// CloudFront Function (viewer request) on /book/*: no valid booking pass, no access to the
// booking API (blueprint step 7). PENDING CloudFront verification.
//
// Checks the X-Booking-Pass header: HMAC-SHA256 signature with the pass key (from the
// CloudFront KeyValueStore, key "pass-key", JSON {kid, key}), type "pass", not expired, and for
// the event in the URL (/book/<event>/...). The booking API checks it again, including that the
// pass belongs to the signed-in user (it verifies the Cognito token, which this function can't).
import cf from 'cloudfront';

const crypto = require('crypto');
const kvs = cf.kvs();

function refuse(reason, eventId) {
  return {
    statusCode: 403,
    statusDescription: 'Forbidden',
    headers: {
      'content-type': { value: 'application/json' },
      'cache-control': { value: 'no-store' },
    },
    body: JSON.stringify({ detail: { reason: reason, queue: '/queue/' + eventId + '/join' } }),
  };
}

async function handler(event) {
  const request = event.request;
  const eventId = request.uri.split('/')[2] || '';
  if (request.method === 'OPTIONS') return request; // CORS preflight carries no pass
  const header = request.headers['x-booking-pass'];
  if (!header) return refuse('booking pass required', eventId);

  const parts = header.value.split('.');
  if (parts.length !== 2) return refuse('booking pass refused: malformed pass', eventId);

  let key;
  try {
    // cloudfront-js-2.0 does not allow `await` inside call arguments: await into a variable first.
    const raw = await kvs.get('pass-key');
    key = JSON.parse(raw);
  } catch (e) {
    return refuse('booking pass refused: verifier not configured', eventId);
  }
  const expected = crypto.createHmac('sha256', key.key).update(parts[0]).digest('base64url');
  if (expected !== parts[1]) return refuse('booking pass refused: forged pass', eventId);

  let payload;
  try {
    payload = JSON.parse(Buffer.from(parts[0], 'base64url').toString('utf8'));
  } catch (e) {
    return refuse('booking pass refused: malformed pass', eventId);
  }
  if (payload.typ !== 'pass' || payload.kid !== key.kid) return refuse('booking pass refused: not a booking pass', eventId);
  if (payload.exp * 1000 < Date.now()) return refuse('booking pass refused: pass expired', eventId);
  if (payload.ev !== eventId) return refuse('booking pass refused: pass is for another event', eventId);
  return request;
}
