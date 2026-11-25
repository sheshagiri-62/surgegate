# ---------------------------------------------------------------------------
# WAF on CloudFront (Day 9 Task 2). Rules are evaluated in priority order; the first
# terminating action (Allow / Block / Challenge) wins.
#
#   0  AllowLoadGenerators   k6 source IPs, only while load_test_enabled (off by default)
#   1  AllowWebhooks         /webhooks/* : server-to-server, authenticated by HMAC, never
#                            challenged or rate-limited (Day 7 note)
#   2  IpReputation          AWS managed: known bad IPs
#   3  RateLimitAll          > rate_limit_per_5min per IP, any path  -> 429
#   4  RateLimitJoin         > join_limit_per_min joins per IP      -> 429
#   5  ChallengeJoin         POST /queue/<event>/join needs a solved challenge (aws-waf-token);
#                            the buyer site gets one with challenge.js, a script can't
#   6  BotControl            AWS managed, COMMON level, ONLY /queue/* (fewer billed requests)
#   7  CommonRuleSet         AWS managed (OWASP-style); body-size rule counted, not blocked
#                            (organisers upload seat-map CSVs)
#
# Prices (Price List API, 25 Nov 2026, global/CloudFront): web ACL $5/month, $1/month per rule,
# $0.60 per million requests, Bot Control $10/month + first 10M requests/month free then
# $1/million, challenges $0.40 per million. All fixed fees prorated hourly.
# ---------------------------------------------------------------------------
locals {
  tags = merge(var.tags, { Component = "waf" })

  join_regex = "^/queue/[^/]+/join$"
}

resource "aws_wafv2_ip_set" "load_generators" {
  count              = length(var.load_test_cidrs) > 0 ? 1 : 0
  name               = "${var.name}-load-generators"
  description        = "k6 load generators - Day 10 tests"
  scope              = "CLOUDFRONT"
  ip_address_version = "IPV4"
  addresses          = var.load_test_cidrs
  tags               = local.tags
}

resource "aws_wafv2_regex_pattern_set" "join" {
  name        = "${var.name}-queue-join"
  description = "POST /queue/event-id/join"
  scope       = "CLOUDFRONT"
  regular_expression {
    regex_string = local.join_regex
  }
  tags = local.tags
}

resource "aws_wafv2_web_acl" "this" {
  name        = var.name
  description = "SurgeGate edge protection - CloudFront"
  scope       = "CLOUDFRONT"

  default_action {
    allow {}
  }

  # A solved challenge stays valid this long (one waiting-room visit).
  challenge_config {
    immunity_time_property {
      immunity_time = var.challenge_immunity_seconds
    }
  }

  # 0 -- load generators (k6) skip everything below, only during a test window
  dynamic "rule" {
    for_each = var.load_test_enabled && length(var.load_test_cidrs) > 0 ? [1] : []
    content {
      name     = "AllowLoadGenerators"
      priority = 0
      action {
        allow {}
      }
      statement {
        ip_set_reference_statement {
          arn = aws_wafv2_ip_set.load_generators[0].arn
        }
      }
      visibility_config {
        cloudwatch_metrics_enabled = true
        metric_name                = "AllowLoadGenerators"
        sampled_requests_enabled   = true
      }
    }
  }

  # 1 -- payment webhooks: never challenged, rate-limited or bot-checked
  rule {
    name     = "AllowWebhooks"
    priority = 1
    action {
      allow {}
    }
    statement {
      byte_match_statement {
        search_string         = "/webhooks/"
        positional_constraint = "STARTS_WITH"
        field_to_match {
          uri_path {}
        }
        text_transformation {
          priority = 0
          type     = "NONE"
        }
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "AllowWebhooks"
      sampled_requests_enabled   = true
    }
  }

  # 2 -- known bad IPs
  rule {
    name     = "IpReputation"
    priority = 2
    override_action {
      none {}
    }
    statement {
      managed_rule_group_statement {
        vendor_name = "AWS"
        name        = "AWSManagedRulesAmazonIpReputationList"
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "IpReputation"
      sampled_requests_enabled   = true
    }
  }

  # 3 -- any path, per client IP
  rule {
    name     = "RateLimitAll"
    priority = 3
    action {
      block {
        custom_response {
          response_code = 429
        }
      }
    }
    statement {
      rate_based_statement {
        limit                 = var.rate_limit_per_5min
        evaluation_window_sec = 300
        aggregate_key_type    = "IP"
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "RateLimitAll"
      sampled_requests_enabled   = true
    }
  }

  # 4 -- joins, per client IP (a script hammering join)
  rule {
    name     = "RateLimitJoin"
    priority = 4
    action {
      block {
        custom_response {
          response_code = 429
        }
      }
    }
    statement {
      rate_based_statement {
        limit                 = var.join_limit_per_min
        evaluation_window_sec = 60
        aggregate_key_type    = "IP"
        scope_down_statement {
          regex_pattern_set_reference_statement {
            arn = aws_wafv2_regex_pattern_set.join.arn
            field_to_match {
              uri_path {}
            }
            text_transformation {
              priority = 0
              type     = "NONE"
            }
          }
        }
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "RateLimitJoin"
      sampled_requests_enabled   = true
    }
  }

  # 5 -- challenge before join: passes with a valid aws-waf-token, otherwise the challenge
  rule {
    name     = "ChallengeJoin"
    priority = 5
    action {
      challenge {}
    }
    statement {
      regex_pattern_set_reference_statement {
        arn = aws_wafv2_regex_pattern_set.join.arn
        field_to_match {
          uri_path {}
        }
        text_transformation {
          priority = 0
          type     = "NONE"
        }
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "ChallengeJoin"
      sampled_requests_enabled   = true
    }
  }

  # 6 -- bots, only on the waiting room
  rule {
    name     = "BotControl"
    priority = 6
    override_action {
      none {}
    }
    statement {
      managed_rule_group_statement {
        vendor_name = "AWS"
        name        = "AWSManagedRulesBotControlRuleSet"
        managed_rule_group_configs {
          aws_managed_rules_bot_control_rule_set {
            inspection_level = "COMMON"
          }
        }
        scope_down_statement {
          byte_match_statement {
            search_string         = "/queue/"
            positional_constraint = "STARTS_WITH"
            field_to_match {
              uri_path {}
            }
            text_transformation {
              priority = 0
              type     = "NONE"
            }
          }
        }
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "BotControl"
      sampled_requests_enabled   = true
    }
  }

  # 7 -- common web exploits
  rule {
    name     = "CommonRuleSet"
    priority = 7
    override_action {
      none {}
    }
    statement {
      managed_rule_group_statement {
        vendor_name = "AWS"
        name        = "AWSManagedRulesCommonRuleSet"
        # Organisers upload seat maps (CSV) bigger than the rule's 8 KB body limit.
        rule_action_override {
          name = "SizeRestrictions_BODY"
          action_to_use {
            count {}
          }
        }
      }
    }
    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "CommonRuleSet"
      sampled_requests_enabled   = true
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = var.name
    sampled_requests_enabled   = true
  }

  tags = local.tags
}

# Logs only what WAF stopped, challenged or counted (allowed traffic is dropped, which keeps a
# 50k-user test from writing gigabytes). The name must start with aws-waf-logs-.
resource "aws_cloudwatch_log_group" "waf" {
  name              = "aws-waf-logs-${var.name}"
  retention_in_days = var.log_retention_days
  tags              = local.tags
}

resource "aws_wafv2_web_acl_logging_configuration" "this" {
  resource_arn            = aws_wafv2_web_acl.this.arn
  log_destination_configs = [aws_cloudwatch_log_group.waf.arn]

  logging_filter {
    default_behavior = "DROP"
    filter {
      behavior    = "KEEP"
      requirement = "MEETS_ANY"
      condition {
        action_condition {
          action = "BLOCK"
        }
      }
      condition {
        action_condition {
          action = "CHALLENGE"
        }
      }
      condition {
        action_condition {
          action = "COUNT"
        }
      }
    }
  }
}
