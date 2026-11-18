{
  description = "Central multi-app F-Droid repository builder and GitHub Pages publisher (hddq's repo)";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
  };

  outputs = { self, nixpkgs }:
    let
      supportedSystems = [
        "x86_64-linux"
        "aarch64-linux"
        "x86_64-darwin"
        "aarch64-darwin"
      ];
      forAllSystems = f: nixpkgs.lib.genAttrs supportedSystems (system: f nixpkgs.legacyPackages.${system});
    in
    {
      devShells = forAllSystems (pkgs:
        let
          pythonEnv = pkgs.python3.withPackages (ps: [
            ps.pyyaml
            ps.requests
            ps.pytest
          ]);
        in
        {
          default = pkgs.mkShell {
            packages = [
              pythonEnv
              pkgs.ruff
              pkgs.fdroidserver
              pkgs.aapt
              pkgs.jdk21_headless
              pkgs.gh
              pkgs.jq
              pkgs.git
              pkgs.curl
            ];

            shellHook = ''
              export PYTHONPATH="$PWD/src''${PYTHONPATH:+:$PYTHONPATH}"
            '';
          };
        });

      packages = forAllSystems (pkgs:
        let
          pythonEnv = pkgs.python3.withPackages (ps: [
            ps.pyyaml
            ps.requests
          ]);
        in
        {
          default = pkgs.python3Packages.buildPythonApplication {
            pname = "fdroid-repo-manager";
            version = "0.1.0";
            pyproject = true;
            src = ./.;

            nativeBuildInputs = [
              pkgs.python3Packages.setuptools
              pkgs.makeWrapper
            ];

            propagatedBuildInputs = [
              pkgs.python3Packages.pyyaml
              pkgs.python3Packages.requests
            ];

            postFixup = ''
              wrapProgram $out/bin/fdroid-repo \
                --prefix PATH : ${pkgs.lib.makeBinPath [
                  pkgs.fdroidserver
                  pkgs.aapt
                  pkgs.jdk21_headless
                  pkgs.git
                  pkgs.curl
                ]}
            '';

            doCheck = false;
          };
        });
    };
}
