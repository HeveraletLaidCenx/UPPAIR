# RUPRAI

**R**'s  
**U**niversal  
**P**ackage  
**R**esolution  
**A**nd  
**I**nstallation

## why?

For some situations, like:

- **trying to strictly follow the environment version given in a paper several years ago**

people have a demand for install **outdated specified versions** of R packages.

but as the answer mentioned in [*pak*'s issue #668](https://github.com/r-lib/pak/issues/668): 

> *"this is how CRAN works. They typically only include the latest versions of packages in their package metadata, "*

most tools only handle non-outdated versions. 

the only way I found to achieve such goal is:

- go to the [Archive directory](https://cran.r-project.org/src/contrib/Archive/) find the packages and check the version and date,
- download the file and install it through: 

    ```bash
    install.packages("<package_name_and_version>.tar.gz", repos = NULL)
    ```
however, this process may further cause dependency problems, making the installation process painful. 

so I hope there'll be a tool that can handle this process better, which is why RUPRAI born.

## how?

