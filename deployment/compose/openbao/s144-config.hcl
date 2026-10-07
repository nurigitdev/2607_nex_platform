ui = true
disable_mlock = true
api_addr = "https://openbao:8200"
cluster_addr = "https://openbao:8201"

storage "raft" {
  path = "/openbao/data"
  node_id = "nex-platform-s144"
}

listener "tcp" {
  address = "0.0.0.0:8200"
  cluster_address = "0.0.0.0:8201"
  tls_cert_file = "/run/secrets/openbao_server_cert"
  tls_key_file = "/run/secrets/openbao_server_key"
  tls_min_version = "tls12"
}
