locals {
  tags       = merge(var.tags, { Component = "edge" })
  use_domain = var.domain_name != ""
  api_fqdn   = local.use_domain ? "${var.api_subdomain}.${var.domain_name}" : null

  # The ALB side only exists while dev is up; CloudFront is persistent (no hourly cost, stable URL).
  alb = var.origin_enabled ? 1 : 0

  # While down, CloudFront still needs an origin. example.com is reserved (RFC 2606) and is never
  # contacted: the "origin-down" function answers 503 at the edge before any origin request.
  placeholder_origin = "example.com"
}

# ---------------------------------------------------------------------------
# ALB security group: only CloudFront's origin-facing IP ranges may connect
# ---------------------------------------------------------------------------
data "aws_ec2_managed_prefix_list" "cloudfront" {
  name = "com.amazonaws.global.cloudfront.origin-facing"
}

resource "aws_security_group" "alb" {
  count       = local.alb
  name        = "${var.name}-alb"
  description = "ALB: HTTP from CloudFront origin-facing ranges only"
  vpc_id      = var.vpc_id
  tags        = merge(local.tags, { Name = "${var.name}-alb" })
}

resource "aws_vpc_security_group_ingress_rule" "alb_from_cloudfront" {
  count             = local.alb
  security_group_id = aws_security_group.alb[0].id
  description       = "HTTP from CloudFront (origin-facing prefix list)"
  prefix_list_id    = data.aws_ec2_managed_prefix_list.cloudfront.id
  ip_protocol       = "tcp"
  from_port         = 80
  to_port           = 80
}

# CloudFront VPC origin: CloudFront creates a service-managed ENI in our private subnets and
# reaches the internal ALB over AWS's network. No extra charge. Follows the ALB (dev up only).
# Still HTTP on that private path: HTTPS needs a certificate, i.e. the domain (later).
resource "aws_cloudfront_vpc_origin" "alb" {
  count = var.cloudfront_enabled ? local.alb : 0

  vpc_origin_endpoint_config {
    name                   = "${var.name}-alb"
    arn                    = aws_lb.this[0].arn
    http_port              = 80
    https_port             = 443
    origin_protocol_policy = "http-only"
    origin_ssl_protocols {
      items    = ["TLSv1.2"]
      quantity = 1
    }
  }

  timeouts {
    create = "30m"
    delete = "30m"
  }

  tags = local.tags
}

# Temporary demo/debug access for ONE address (e.g. to show live that a request without the
# secret header gets 403). Empty by default; never set it in committed code.
resource "aws_vpc_security_group_ingress_rule" "alb_debug" {
  count             = var.debug_ingress_cidr != "" ? local.alb : 0
  security_group_id = aws_security_group.alb[0].id
  description       = "TEMPORARY debug access (remove after use)"
  cidr_ipv4         = var.debug_ingress_cidr
  ip_protocol       = "tcp"
  from_port         = 80
  to_port           = 80
}

resource "aws_vpc_security_group_egress_rule" "alb_to_pods" {
  count                        = local.alb
  security_group_id            = aws_security_group.alb[0].id
  description                  = "To booking-api pods"
  referenced_security_group_id = var.node_security_group_id
  ip_protocol                  = "tcp"
  from_port                    = var.target_port
  to_port                      = var.target_port
}

resource "aws_vpc_security_group_ingress_rule" "nodes_from_alb" {
  count                        = local.alb
  security_group_id            = var.node_security_group_id
  description                  = "booking-api pods from the ALB"
  referenced_security_group_id = aws_security_group.alb[0].id
  ip_protocol                  = "tcp"
  from_port                    = var.target_port
  to_port                      = var.target_port
}

# ---------------------------------------------------------------------------
# ALB: owned by Terraform (not by an Ingress) so the secret header rule never sits in Git,
# and make down removes it. Pods join the target group through a TargetGroupBinding.
# ---------------------------------------------------------------------------
resource "aws_lb" "this" {
  count              = local.alb
  name               = "${var.name}-api"
  load_balancer_type = "application"
  # Internal: no public address. CloudFront reaches it through a VPC origin (ADR 003 follow-up:
  # the CloudFront -> ALB hop no longer crosses the internet). Without CloudFront it stays public.
  internal                   = var.cloudfront_enabled
  subnets                    = var.cloudfront_enabled ? var.private_subnet_ids : var.public_subnet_ids
  security_groups            = [aws_security_group.alb[0].id]
  drop_invalid_header_fields = true
  tags                       = local.tags
}

resource "aws_lb_target_group" "api" {
  count                = local.alb
  name                 = var.target_group_name
  port                 = var.target_port
  protocol             = "HTTP"
  target_type          = "ip" # pod IPs (VPC CNI)
  vpc_id               = var.vpc_id
  deregistration_delay = 30

  health_check {
    path                = var.health_check_path
    matcher             = "200"
    interval            = 10
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  tags = local.tags
}

resource "aws_lb_listener" "http" {
  count             = local.alb
  load_balancer_arn = aws_lb.this[0].arn
  port              = 80
  protocol          = "HTTP"

  # Anything without the secret header (i.e. not via our CloudFront) is refused.
  default_action {
    type = "fixed-response"
    fixed_response {
      content_type = "text/plain"
      message_body = "Forbidden"
      status_code  = "403"
    }
  }

  tags = local.tags
}

resource "aws_lb_listener_rule" "from_cloudfront" {
  count        = local.alb
  listener_arn = aws_lb_listener.http[0].arn
  priority     = 10

  condition {
    http_header {
      http_header_name = var.origin_verify_header_name
      values           = [var.origin_verify_secret]
    }
  }

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api[0].arn
  }

  tags = local.tags
}

# More services on the same ALB (e.g. mock-pay's public checkout page, ADR 004): only the
# listed paths, and only with the origin-verify header (i.e. through our CloudFront).
resource "aws_lb_target_group" "extra" {
  for_each             = local.alb == 1 ? var.extra_routes : {}
  name                 = "${var.name}-${each.key}"
  port                 = var.target_port
  protocol             = "HTTP"
  target_type          = "ip"
  vpc_id               = var.vpc_id
  deregistration_delay = 10

  health_check {
    path                = each.value.health_check_path
    matcher             = "200"
    interval            = 10
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  tags = local.tags
}

resource "aws_lb_listener_rule" "extra" {
  for_each     = aws_lb_target_group.extra
  listener_arn = aws_lb_listener.http[0].arn
  priority     = var.extra_routes[each.key].priority

  condition {
    http_header {
      http_header_name = var.origin_verify_header_name
      values           = [var.origin_verify_secret]
    }
  }

  condition {
    path_pattern {
      values = var.extra_routes[each.key].path_patterns
    }
  }

  action {
    type             = "forward"
    target_group_arn = each.value.arn
  }

  tags = local.tags
}

# ---------------------------------------------------------------------------
# Optional own domain: Route 53 zone + ACM certificate (us-east-1) + alias records
# ---------------------------------------------------------------------------
resource "aws_route53_zone" "this" {
  count = local.use_domain ? 1 : 0
  name  = var.domain_name
  tags  = local.tags
}

resource "aws_acm_certificate" "api" {
  count             = local.use_domain ? 1 : 0
  provider          = aws.us_east_1
  domain_name       = local.api_fqdn
  validation_method = "DNS"
  tags              = local.tags

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_route53_record" "cert_validation" {
  for_each = local.use_domain ? {
    for o in aws_acm_certificate.api[0].domain_validation_options : o.domain_name => o
  } : {}

  zone_id = aws_route53_zone.this[0].zone_id
  name    = each.value.resource_record_name
  type    = each.value.resource_record_type
  records = [each.value.resource_record_value]
  ttl     = 300
}

resource "aws_acm_certificate_validation" "api" {
  count                   = local.use_domain ? 1 : 0
  provider                = aws.us_east_1
  certificate_arn         = aws_acm_certificate.api[0].arn
  validation_record_fqdns = [for r in aws_route53_record.cert_validation : r.fqdn]
}

# ---------------------------------------------------------------------------
# CloudFront (persistent): HTTPS to viewers; adds the secret header to origin requests.
# ---------------------------------------------------------------------------
data "aws_cloudfront_cache_policy" "disabled" {
  name = "Managed-CachingDisabled" # API responses are dynamic; caching comes in Phase 3 (/serving)
}

data "aws_cloudfront_origin_request_policy" "all_viewer_except_host" {
  name = "Managed-AllViewerExceptHostHeader"
}

# Waiting room "now serving" counter: identical for everyone, so cache it for 5 seconds at the
# edge (blueprint step 5: 5,000 polls a second become a handful of origin calls).
# PENDING CloudFront verification: created only when cloudfront_enabled.
resource "aws_cloudfront_cache_policy" "serving" {
  count       = var.cloudfront_enabled && var.queue_api_domain != "" ? 1 : 0
  name        = "${var.name}-queue-serving-5s"
  comment     = "GET /queue/{event}/serving: shared counter, 5 s"
  min_ttl     = 0
  default_ttl = 5
  max_ttl     = 5

  parameters_in_cache_key_and_forwarded_to_origin {
    enable_accept_encoding_gzip   = true
    enable_accept_encoding_brotli = true
    cookies_config {
      cookie_behavior = "none"
    }
    headers_config {
      header_behavior = "none" # no Authorization: the counter is public and the same for all
    }
    query_strings_config {
      query_string_behavior = "none"
    }
  }
}

# Booking pass at the edge (blueprint step 7): requests to /book/* without a valid pass are
# refused by CloudFront and never reach the cluster. PENDING CloudFront verification.
# The pass key is copied into the KeyValueStore once after verification (see the Day 6 Task 2
# report): Terraform never holds its value (write-only secret).
resource "aws_cloudfront_key_value_store" "edge" {
  count   = var.cloudfront_enabled ? 1 : 0
  name    = "${var.name}-edge"
  comment = "Keys the edge needs (pass-key: booking-pass HMAC key)"
}

resource "aws_cloudfront_function" "booking_pass" {
  count                        = var.cloudfront_enabled ? 1 : 0
  name                         = "${var.name}-booking-pass"
  runtime                      = "cloudfront-js-2.0"
  comment                      = "Refuse /book/* without a valid booking pass"
  publish                      = true
  code                         = file("${path.module}/functions/booking_pass.js")
  key_value_store_associations = [aws_cloudfront_key_value_store.edge[0].arn]
}

# Attached only while the ALB doesn't exist: a clear 503 instead of a confusing 502.
resource "aws_cloudfront_function" "origin_down" {
  name    = "${var.name}-origin-down"
  runtime = "cloudfront-js-2.0"
  comment = "503 while the dev environment is down (make down)"
  publish = true
  code    = <<-JS
    function handler(event) {
      return {
        statusCode: 503,
        statusDescription: "Service Unavailable",
        headers: {
          "content-type": { value: "application/json" },
          "cache-control": { value: "no-store" },
          "retry-after": { value: "900" }
        },
        body: '{"status":"unavailable","reason":"dev environment is down (make up to start)"}'
      };
    }
  JS
}

resource "aws_cloudfront_distribution" "api" {
  count           = var.cloudfront_enabled ? 1 : 0
  enabled         = true
  is_ipv6_enabled = true
  comment         = "${var.name} booking API"
  price_class     = var.price_class
  aliases         = local.use_domain ? [local.api_fqdn] : []

  origin {
    origin_id   = "api"
    domain_name = var.origin_enabled ? aws_lb.this[0].dns_name : local.placeholder_origin

    # Dev up: the internal ALB through the VPC origin (private path inside AWS).
    dynamic "vpc_origin_config" {
      for_each = var.origin_enabled ? [1] : []
      content {
        vpc_origin_id = aws_cloudfront_vpc_origin.alb[0].id
      }
    }

    # Dev down: a placeholder (the origin_down function answers 503 before it is used).
    dynamic "custom_origin_config" {
      for_each = var.origin_enabled ? [] : [1]
      content {
        http_port              = 80
        https_port             = 443
        origin_protocol_policy = "http-only"
        origin_ssl_protocols   = ["TLSv1.2"]
      }
    }

    custom_header {
      name  = var.origin_verify_header_name
      value = var.origin_verify_secret
    }
  }

  # Waiting room API (API Gateway), same origin as the site for browsers.
  dynamic "origin" {
    for_each = var.queue_api_domain != "" ? [1] : []
    content {
      origin_id   = "queue"
      domain_name = var.queue_api_domain
      custom_origin_config {
        http_port              = 80
        https_port             = 443
        origin_protocol_policy = "https-only"
        origin_ssl_protocols   = ["TLSv1.2"]
      }
    }
  }

  # Most specific first: the cached counter, then the rest of the queue API (never cached).
  dynamic "ordered_cache_behavior" {
    for_each = var.queue_api_domain != "" ? [1] : []
    content {
      path_pattern           = "/queue/*/serving"
      target_origin_id       = "queue"
      viewer_protocol_policy = "redirect-to-https"
      allowed_methods        = ["GET", "HEAD", "OPTIONS"]
      cached_methods         = ["GET", "HEAD"]
      cache_policy_id        = aws_cloudfront_cache_policy.serving[0].id
      compress               = true
    }
  }

  dynamic "ordered_cache_behavior" {
    for_each = var.queue_api_domain != "" ? [1] : []
    content {
      path_pattern             = "/queue/*"
      target_origin_id         = "queue"
      viewer_protocol_policy   = "redirect-to-https"
      allowed_methods          = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
      cached_methods           = ["GET", "HEAD"]
      cache_policy_id          = data.aws_cloudfront_cache_policy.disabled.id
      origin_request_policy_id = data.aws_cloudfront_origin_request_policy.all_viewer_except_host.id
      compress                 = true
    }
  }

  # /book/*: booking API, only with a valid booking pass (checked here, then again in the API).
  ordered_cache_behavior {
    path_pattern             = "/book/*"
    target_origin_id         = "api"
    viewer_protocol_policy   = "redirect-to-https"
    allowed_methods          = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods           = ["GET", "HEAD"]
    cache_policy_id          = data.aws_cloudfront_cache_policy.disabled.id
    origin_request_policy_id = data.aws_cloudfront_origin_request_policy.all_viewer_except_host.id
    compress                 = true

    function_association {
      event_type   = "viewer-request"
      function_arn = var.origin_enabled ? aws_cloudfront_function.booking_pass[0].arn : aws_cloudfront_function.origin_down.arn
    }
  }

  default_cache_behavior {
    target_origin_id         = "api"
    viewer_protocol_policy   = "redirect-to-https"
    allowed_methods          = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods           = ["GET", "HEAD"]
    cache_policy_id          = data.aws_cloudfront_cache_policy.disabled.id
    origin_request_policy_id = data.aws_cloudfront_origin_request_policy.all_viewer_except_host.id
    compress                 = true

    dynamic "function_association" {
      for_each = var.origin_enabled ? [] : [1]
      content {
        event_type   = "viewer-request"
        function_arn = aws_cloudfront_function.origin_down.arn
      }
    }
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = !local.use_domain
    acm_certificate_arn            = local.use_domain ? aws_acm_certificate_validation.api[0].certificate_arn : null
    ssl_support_method             = local.use_domain ? "sni-only" : null
    minimum_protocol_version       = local.use_domain ? "TLSv1.2_2021" : "TLSv1"
  }

  tags = local.tags
}

resource "aws_route53_record" "api_alias" {
  for_each = local.use_domain && var.cloudfront_enabled ? toset(["A", "AAAA"]) : toset([])

  zone_id = aws_route53_zone.this[0].zone_id
  name    = local.api_fqdn
  type    = each.key

  alias {
    name                   = aws_cloudfront_distribution.api[0].domain_name
    zone_id                = aws_cloudfront_distribution.api[0].hosted_zone_id
    evaluate_target_health = false
  }
}
