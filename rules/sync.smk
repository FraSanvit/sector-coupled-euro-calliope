# Rules to sync to and from cluster


rule send:
    message: "Send changes to cluster"
    params:
        send_ignore = config["cluster-sync"]["send-ignore"],
        url = config["cluster-sync"]["url"],
        cluster_base_dir = config["cluster-sync"]["cluster-base-dir"]
    shell:
        """
        rsync -avzh --progress --delete -r . --exclude-from={params.send_ignore} \
        {params.url}:{params.cluster_base_dir}
        """


rule receive:
    message: "Receive build changes from cluster"
    params:
        send_ignore = config["cluster-sync"]["send-ignore"],
        receive_ignore = config["cluster-sync"]["receive-ignore"],
        url = config["cluster-sync"]["url"],
        cluster_base_dir = config["cluster-sync"]["cluster-base-dir"],
        cluster_build_dir = config["cluster-sync"]["cluster-base-dir"] + "/build/",
        local_results_dir = config["cluster-sync"]["local-results-dir"]
    shell:
        """
        rsync -avzh --progress --max-size=400m --delete -r --exclude-from={params.receive_ignore} \
        {params.url}:{params.cluster_build_dir} {params.local_results_dir}
        """

rule receive_pre_builds:
    message: "Receive build changes from cluster"
    params:
        url = config["cluster-sync"]["url"],
        cluster_build_dir = config["cluster-sync"]["cluster-base-dir"] + "/build/",
        local_results_dir = config["cluster-sync"]["local-results-dir"]
    shell:
        """
        rsync -avzh --progress --delete -r --include="*.zip" --exclude="*" \
        {params.url}:{params.cluster_build_dir} {params.local_results_dir}
        """


rule clean_cluster_results:
    message: "Clean results downloaded from cluster"
    params:
        local_results_dir = config["cluster-sync"]["local-results-dir"]
    shell:
        "rm -r {params.local_results_dir}"
