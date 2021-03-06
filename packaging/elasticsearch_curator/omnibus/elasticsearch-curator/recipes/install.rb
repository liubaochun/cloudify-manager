
# reload ohai data
ohai 'reload' do
  action :reload
end

pkg_path = Dir.glob("#{node['etc']['passwd']['vagrant']['dir']}/cloudify/pkg/cloudify*rpm")[0] if node['platform_family'] == 'rhel'

package 'elasticsearch-curator' do
  action :install
  source pkg_path
end
