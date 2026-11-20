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
  count                      = local.alb
  name                       = "${var.name}-api"
  load_balancer_type         = "application"
  internal                   = false
  subnets                    = var.public_subnet_ids
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
  enabled         = true
  is_ipv6_enabled = true
  comment         = "${var.name} booking API"
  price_class     = var.price_class
  aliases         = local.use_domain ? [local.api_fqdn] : []

  origin {
    origin_id   = "api"
    domain_name = var.origin_enabled ? aws_lb.this[0].dns_name : local.placeholder_origin

    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "http-only" # no domain → no certificate on the ALB (see ADR 003)
      origin_ssl_protocols   = ["TLSv1.2"]
    }

    custom_header {
      name  = var.origin_verify_header_name
      value = var.origin_verify_secret
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
  for_each = local.use_domain ? toset(["A", "AAAA"]) : toset([])

  zone_id = aws_route53_zone.this[0].zone_id
  name    = local.api_fqdn
  type    = each.key

  alias {
    name                   = aws_cloudfront_distribution.api.domain_name
    zone_id                = aws_cloudfront_distribution.api.hosted_zone_id
    evaluate_target_health = false
  }
}
