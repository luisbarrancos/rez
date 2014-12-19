from rez.utils.resources import ResourcePool
from rez.utils.data_utils import cached_property
from rez.plugin_managers import plugin_manager
from rez.config import config
from rez.backport.lru_cache import lru_cache
import os.path


def get_package_repository_types():
    """Returns the available package repository implementations."""
    return plugin_manager.get_plugins('package_repository')


class PackageRepository(object):
    """Base class for package repositories implemented in the package_repository
    plugin type.
    """
    @classmethod
    def name(cls):
        """Return the name of the package repository type."""
        raise NotImplementedError

    def __init__(self, location, resource_pool):
        """Create a package repository.

        Args:
            location (str): A string specifying the location of the repository.
                This could be a filesystem path, or a database uri, etc.
            resource_pool (`ResourcePool`): The pool used to manage package
                resources.
        """
        self.location = location
        self.pool = resource_pool

    def register_resource(self, resource_class):
        """Register a resource with the repository.

        Your derived repository class should call this method in its __init__ to
        register all the resource types associated with that plugin.
        """
        self.pool.register_resource(resource_class)

    @cached_property
    def uid(self):
        """Returns a unique identifier for this repository.

        This is necessary for memcached caching.

        Returns:
            hashable value: Value that uniquely identifies this repository.
        """
        return self._uid()

    def get_package_family(self, name):
        """Get a package family.

        Args:
            name (str): Package name.

        Returns:
            `PackageFamilyResource`, or None if not found.
        """
        raise NotImplementedError

    def iter_package_families(self):
        """Iterate over the package families in the repository, in no
        particular order.

        Returns:
            `PackageFamilyResource` iterator.
        """
        raise NotImplementedError

    def iter_packages(self, package_family_resource):
        """Iterate over the packages within the given family, in no particular
        order.

        Args:
            package_family_resource (`PackageFamilyResource`): Parent family.

        Returns:
            `PackageResource` iterator.
        """
        raise NotImplementedError

    def iter_variants(self, package_resource):
        """Iterate over the variants within the given package.

        Args:
            package_resource (`PackageResource`): Parent package.

        Returns:
            `VariantResource` iterator.
        """
        raise NotImplementedError

    def get_parent_package_family(self, package_resource):
        """Get the parent package family of the given package.

        Args:
            package_resource (`PackageResource`): Package.

        Returns:
            `PackageFamilyResource`.
        """
        raise NotImplementedError

    def get_parent_package(self, variant_resource):
        """Get the parent package of the given variant.

        Args:
            variant_resource (`VariantResource`): Variant.

        Returns:
            `PackageResource`.
        """
        raise NotImplementedError

    def get_developer_package(self):
        """Get the developer package.

        Note:
            Most repositories will not need to implement this.

        This is implemented by the 'filesystem' repository. It loads a package
        from a working directory, before the package has been installed or
        released.

        Returns:
            `PackageResource`.
        """
        raise NotImplementedError

    def get_variant_state_handle(self, variant_resource):
        """Get a value that indicates the state of the variant.

        This is used for resolve caching. For example, in the 'filesystem'
        repository type, the 'state' is the last modified date of the file
        associated with the variant (perhaps a package.py). If the state of
        any variant has changed from a cached resolve - eg, if a file has been
        modified - the cached resolve is discarded.

        This may not be applicable to your repository type, leave as-is if so.

        Returns:
            A hashable value.
        """
        return None

    def get_last_release_time(self, package_family_resource):
        """Get the last time a package was added to the given family.

        This information is used to cache resolves via memcached. It can be left
        not implemented, but resolve caching is a substantial optimisation that
        you will be missing out on.

        Returns:
            int: Epoch time at which a package was changed/added/removed from
                the given package family. Zero signifies an unknown last package
                update time.
        """
        return 0

    def get_resource(self, resource_handle):
        resource = self.pool.get_resource_from_handle(resource_handle)
        resource._repository = self
        return resource

    def _uid(self):
        """Unique identifier implementation.

        You may need to provide your own implementation. For example, consider
        the 'filesystem' repository. A default uri might be 'filesystem:/tmp_pkgs'.
        However /tmp_pkgs is probably a local path for each user, so this would
        not actually uniquely identify the repository - probably the inode number
        needs to be incorporated also.

        Returns:
            Hashable value.
        """
        return (self.name(), self.location)


class PackageRepositoryManager(object):
    """Package repository manager.

    Contains instances of `PackageRepository` for each repository pointed to
    by the 'packages_path' config setting (also commonly set using the
    environment variable REZ_PACKAGES_PATH).
    """
    def __init__(self):
        cache_size = config.resource_caching_maxsize
        if cache_size < 0:
            cache_size = None
        self.pool = ResourcePool(cache_size=cache_size)

    @lru_cache(maxsize=None)
    def get_repository(self, path):
        """Get a package repository.

        Args:
            path (str): Entry from the 'packages_path' config setting. This may
                simply be a path (which is managed by the 'filesystem' package
                repository plugin), or a string in the form "type:location",
                where 'type' identifies the repository plugin type to use.

        Returns:
            `PackageRepository` instance.
        """
        # normalise
        parts = path.split(':', 1)
        if len(parts) == 1:
            parts = ("filesystem", parts[0])

        repo_type, location = parts
        if repo_type == "filesystem":
            location = os.path.realpath(location)

        uri = "%s:%s" % (repo_type, location)
        return self._get_repository(uri)

    def get_resource(self, resource_handle):
        """Get a resource.

        Args:
            resource_handle (`ResourceHandle`): Handle of the resource.

        Returns:
            `PackageRepositoryResource` instance.
        """
        repo_type = resource_handle.get("repository_type")
        location = resource_handle.get("location")
        path = "%s:%s" % (repo_type, location)

        repo = self.get_repository(path)
        resource = repo.get_resource(resource_handle)
        return resource

    def clear_caches(self):
        """Clear all cached data."""
        self.get_repository.cache_clear()
        self._get_repository.cache_clear()
        self.pool.clear_caches()

    @lru_cache(maxsize=None)
    def _get_repository(self, path):
        repo_type, location = path.split(':', 1)
        cls = plugin_manager.get_plugin_class('package_repository', repo_type)
        repo = cls(location, self.pool)
        return repo


# singleton
package_repository_manager = PackageRepositoryManager()