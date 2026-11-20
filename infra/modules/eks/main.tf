data "aws_region" "current" {}

locals {
  tags     = merge(var.tags, { Component = "eks" })
  lbc_sa   = "aws-load-balancer-controller"
  admin    = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSClusterAdminPolicy"
  view_all = "arn:aws:eks::aws:cluster-access-policy/AmazonEKSAdminViewPolicy"
}

# ---------------------------------------------------------------------------
# Cluster + managed node group (community module, pinned)
# ---------------------------------------------------------------------------
module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 21.30"

  name               = var.name
  kubernetes_version = var.kubernetes_version

  vpc_id                   = var.vpc_id
  subnet_ids               = var.private_subnet_ids
  control_plane_subnet_ids = var.private_subnet_ids

  # API reachable from the laptop and GitHub runners; every call still needs IAM auth.
  endpoint_public_access  = true
  endpoint_private_access = true

  # Access entries (not the old aws-auth ConfigMap). Explicit principals instead of
  # "whoever created the cluster", so local and CI applies don't fight over it.
  authentication_mode                      = "API"
  enable_cluster_creator_admin_permissions = false
  access_entries = merge(
    { for i, arn in var.admin_principal_arns : "admin-${i}" => {
      principal_arn = arn
      policy_associations = {
        admin = { policy_arn = local.admin, access_scope = { type = "cluster" } }
      }
    } },
    { for i, arn in var.viewer_principal_arns : "viewer-${i}" => {
      principal_arn = arn
      policy_associations = {
        view = { policy_arn = local.view_all, access_scope = { type = "cluster" } }
      }
    } },
  )

  # Pod Identity instead of IRSA, so no IAM OIDC provider for the cluster.
  enable_irsa = false

  # EKS encrypts Kubernetes secrets by default with an AWS-owned key. A customer KMS key would
  # cost $1/month and sit in a 7–30 day deletion window after every make down.
  create_kms_key           = false
  encryption_config        = null
  attach_encryption_policy = false

  enabled_log_types                      = ["audit", "authenticator"]
  cloudwatch_log_group_retention_in_days = var.log_retention_days

  addons = {
    vpc-cni                = { most_recent = true, before_compute = true }
    eks-pod-identity-agent = { most_recent = true, before_compute = true }
    kube-proxy             = { most_recent = true }
    coredns                = { most_recent = true }
  }

  eks_managed_node_groups = {
    default = {
      ami_type       = "AL2023_x86_64_STANDARD"
      instance_types = var.node_instance_types
      capacity_type  = "ON_DEMAND"

      min_size     = var.node_min_size
      desired_size = var.node_desired_size
      max_size     = var.node_max_size

      block_device_mappings = {
        xvda = {
          device_name = "/dev/xvda"
          ebs = {
            volume_size           = var.node_disk_size_gb
            volume_type           = "gp3"
            encrypted             = true
            delete_on_termination = true
          }
        }
      }

      labels = { "surgegate.io/pool" = "default" }
    }
  }

  tags = local.tags
}

# ---------------------------------------------------------------------------
# AWS Load Balancer Controller: IAM role via Pod Identity, installed with Helm
# ---------------------------------------------------------------------------
module "lbc_pod_identity" {
  source  = "terraform-aws-modules/eks-pod-identity/aws"
  version = "~> 2.11"

  name                            = "${var.name}-aws-lbc"
  attach_aws_lb_controller_policy = true

  associations = {
    lbc = {
      cluster_name    = module.eks.cluster_name
      namespace       = "kube-system"
      service_account = local.lbc_sa
    }
  }

  tags = local.tags
}

resource "helm_release" "lbc" {
  name       = "aws-load-balancer-controller"
  repository = "https://aws.github.io/eks-charts"
  chart      = "aws-load-balancer-controller"
  version    = var.lbc_chart_version
  namespace  = "kube-system"

  set = [
    { name = "clusterName", value = module.eks.cluster_name },
    { name = "region", value = data.aws_region.current.region },
    { name = "vpcId", value = var.vpc_id },
    { name = "serviceAccount.name", value = local.lbc_sa },
    { name = "replicaCount", value = tostring(var.lbc_replicas) },
  ]

  wait    = true
  timeout = 600

  # Nodes, add-ons and the Pod Identity association must exist before the controller starts.
  depends_on = [module.eks, module.lbc_pod_identity]
}

# ---------------------------------------------------------------------------
# Argo CD (GitOps): installed by Terraform, then it deploys everything under deploy/argocd
# ---------------------------------------------------------------------------
resource "helm_release" "argocd" {
  name             = "argocd"
  repository       = "https://argoproj.github.io/argo-helm"
  chart            = "argo-cd"
  version          = var.argocd_chart_version
  namespace        = "argocd"
  create_namespace = true

  # Lean dev install: one replica each, no Dex (SSO) or notifications. TLS ends at the ALB
  # later, and for now the UI is reached with kubectl port-forward.
  values = [yamlencode({
    dex           = { enabled = false }
    notifications = { enabled = false }
    configs = {
      params = { "server.insecure" = true }
      cm     = { "timeout.reconciliation" = "60s" } # poll Git every minute
    }
  })]

  wait    = true
  timeout = 600

  depends_on = [module.eks, helm_release.lbc]
}

# The root "app of apps": one Application that syncs every Application manifest in
# deploy/argocd, so adding a service is a Git commit, not a Terraform change.
resource "helm_release" "argocd_root_app" {
  name       = "argocd-root-app"
  repository = "https://argoproj.github.io/argo-helm"
  chart      = "argocd-apps"
  version    = var.argocd_apps_chart_version
  namespace  = "argocd"

  values = [yamlencode({
    applications = {
      root = {
        namespace = "argocd"
        project   = "default"
        source = {
          repoURL        = var.gitops_repo_url
          targetRevision = var.gitops_revision
          path           = var.gitops_path
          directory      = { recurse = false, include = "*.yaml" }
        }
        destination = { server = "https://kubernetes.default.svc", namespace = "argocd" }
        syncPolicy = {
          automated   = { prune = true, selfHeal = true }
          syncOptions = ["CreateNamespace=true"]
        }
      }
    }
  })]

  depends_on = [helm_release.argocd] # needs the Application CRD
}
