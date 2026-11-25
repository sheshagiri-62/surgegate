// Buyer site (Next.js static export, trailingSlash: true) on S3 behind CloudFront.
// S3 through an origin access control has no "index document", so map page URLs to their files:
//   /            -> /index.html
//   /event/      -> /event/index.html
//   /event       -> /event/index.html   (no dot in the last segment = a page, not a file)
//   /_next/static/chunks/app.js -> unchanged
// The query string (?id=...) is left as it is. Only the default (S3) behaviour runs this.
function handler(event) {
  var request = event.request;
  var uri = request.uri;
  if (uri.endsWith("/")) {
    request.uri = uri + "index.html";
  } else if (uri.lastIndexOf(".") <= uri.lastIndexOf("/")) {
    request.uri = uri + "/index.html";
  }
  return request;
}
