# The load-generator IP set became a single resource (no count) on 25 Nov.
moved {
  from = module.waf[0].aws_wafv2_ip_set.load_generators[0]
  to   = module.waf[0].aws_wafv2_ip_set.load_generators
}
