# ---------------------------------------------------------------------------
# Karpenter (demo only): adds right-sized nodes within seconds when pods are pending (a sale's
# pre-scaling or a spike) and removes them when empty. The managed node group keeps the
# baseline and runs Karpenter itself.
#   - controller IAM role via Pod Identity, node IAM role + EKS access entry, an SQS
#     interruption queue fed by EventBridge (Spot interruptions, rebalance, instance health):
#     community submodule, same pinned version as the cluster module
#   - Helm chart from Karpenter's public OCI registry
#   - NodePool + EC2NodeClass from the small local chart in charts/karpenter-nodes
# ---------------------------------------------------------------------------
module "karpenter" {
  source  = "terraform-aws-modules/eks/aws//modules/karpenter"
  version = "~> 21.30"
  count   = var.enable_karpenter ? 1 : 0

  cluster_name                    = module.eks.cluster_name
  namespace                       = "kube-system"
  create_pod_identity_association = true

  # Fixed name: the EC2NodeClass refers to it.
  node_iam_role_use_name_prefix = false
  node_iam_role_name            = "${var.name}-karpenter-node"
  node_iam_role_additional_policies = {
    AmazonSSMManagedInstanceCore = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
  }

  tags = local.tags
}

resource "helm_release" "karpenter" {
  count      = var.enable_karpenter ? 1 : 0
  name       = "karpenter"
  repository = "oci://public.ecr.aws/karpenter"
  chart      = "karpenter"
  version    = var.karpenter_chart_version
  namespace  = "kube-system"

  values = [yamlencode({
    nodeSelector = { "karpenter.sh/controller" = "true" }
    dnsPolicy    = "Default" # resolve before CoreDNS has capacity
    replicas     = 1         # demo; 2 for production
    settings = {
      clusterName       = module.eks.cluster_name
      clusterEndpoint   = module.eks.cluster_endpoint
      interruptionQueue = module.karpenter[0].queue_name
    }
  })]

  wait    = true
  timeout = 600

  depends_on = [module.eks, module.karpenter]
}

resource "helm_release" "karpenter_nodes" {
  count     = var.enable_karpenter ? 1 : 0
  name      = "karpenter-nodes"
  chart     = "${path.module}/charts/karpenter-nodes"
  namespace = "kube-system"

  values = [yamlencode({
    clusterName   = module.eks.cluster_name
    nodeRole      = module.karpenter[0].node_iam_role_name
    cpuLimit      = var.karpenter_cpu_limit
    instanceTypes = var.karpenter_instance_types
    capacityTypes = var.karpenter_capacity_types
    tags          = merge(var.tags, { Component = "eks", "karpenter.sh/discovery" = var.name })
    loadgen = {
      enabled       = var.karpenter_loadgen_enabled
      cpuLimit      = var.karpenter_loadgen_cpu_limit
      instanceTypes = var.karpenter_loadgen_instance_types
    }
  })]

  depends_on = [helm_release.karpenter] # needs the NodePool / EC2NodeClass CRDs
}
