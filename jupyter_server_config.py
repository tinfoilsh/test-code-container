c = get_config()  # noqa

c.ServerApp.allow_origin = "*"
c.ServerApp.allow_remote_access = True
c.ServerApp.disable_check_xsrf = True
c.ServerApp.allow_root = True
c.ServerApp.iopub_data_rate_limit = 1000000000
