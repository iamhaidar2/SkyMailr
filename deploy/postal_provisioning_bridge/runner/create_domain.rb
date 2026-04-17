# frozen_string_literal: true
# Run inside Postal's app directory: bundle exec rails runner path/to/create_domain.rb <fqdn>
# Required in Postal's environment: POSTAL_ORG_PERMALINK, POSTAL_SERVER_PERMALINK
# Optional: POSTAL_AUTO_VERIFY=true to mark domain verified immediately (trusted operator only).

begin
  name = ARGV[0].to_s.strip.downcase
  raise "missing domain argument" if name.empty?

  org = Organization.find_by(permalink: ENV.fetch("POSTAL_ORG_PERMALINK"))
  raise "organization not found" unless org

  server = org.servers.find_by(permalink: ENV.fetch("POSTAL_SERVER_PERMALINK"))
  raise "server not found" unless server

  existing = server.domains.where("LOWER(domains.name) = ?", name).first
  created = existing.nil?
  domain = existing || server.domains.build(name: name, verification_method: "DNS")

  if domain.new_record?
    domain.save!
  end

  if ENV["POSTAL_AUTO_VERIFY"].to_s == "true" && !domain.verified?
    domain.update_columns(verified_at: Time.current)
  end

  domain.reload

  drn = domain.dkim_record_name.to_s
  dkim_sel = drn.sub(/\._domainkey\z/i, "")

  dns = {
    spf_txt_expected: domain.spf_record,
    dkim_selector: dkim_sel,
    dkim_txt_value: domain.dkim_record.to_s
  }
  dns.compact!

  rp = domain.return_path_domain.to_s
  if rp.present?
    dns[:return_path_cname_name] = rp
  end

  unless domain.verified?
    dns[:postal_verification_txt_expected] = domain.dns_verification_string
  end

  out = {
    ok: true,
    outcome: created ? "created" : "already_exists",
    provider_domain_id: domain.uuid,
    dns: dns,
    # SkyMailr: when true, ownership TXT is omitted from dns on purpose (already verified in Postal).
    postal_domain_verified: domain.verified?
  }

  puts out.to_json
rescue StandardError => e
  warn e.full_message
  warn e.backtrace&.first(8)&.join("\n")
  puts({ ok: false, error_code: "rails_runner_error", error_detail: e.message.to_s[0, 2000] }.to_json)
  exit 1
end
